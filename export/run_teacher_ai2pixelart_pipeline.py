#!/usr/bin/env python3
"""High-quality true-bitmap Pixel Art pipeline.

Pipeline:
  source image
    -> aspect-preserving resize to target_long_edge * teacher_scale
    -> WuZongWei6/Pixelization ONNX teacher
    -> ai2pixelart cleanup (simple/robust/detail)
    -> clamp cleaned bitmap to target_long_edge with NEAREST if needed
    -> save raw bitmap PNG (no upscale)

The final PNG's file pixels are the product pixels. No preview upscale, no /4x4
lattice postprocess.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image
from tqdm import tqdm

EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def aspect_size(w: int, h: int, long_edge: int, multiple: int = 4) -> tuple[int, int]:
    if w <= 0 or h <= 0:
        raise ValueError("invalid image dimensions")
    if w >= h:
        short = max(multiple, round((h * long_edge / w) / multiple) * multiple)
        return long_edge, short
    short = max(multiple, round((w * long_edge / h) / multiple) * multiple)
    return short, long_edge


def clamp_long_edge(img: Image.Image, long_edge: int) -> Image.Image:
    if max(img.size) == long_edge:
        return img
    tw, th = aspect_size(*img.size, long_edge, multiple=1)
    return img.resize((tw, th), Image.Resampling.NEAREST)


def pil_to_nchw(img: Image.Image) -> np.ndarray:
    arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 127.5 - 1.0
    return np.transpose(arr, (2, 0, 1))[None]


def tensor_to_rgb(out: np.ndarray) -> np.ndarray:
    arr = np.transpose(out[0], (1, 2, 0))
    return np.clip((arr + 1.0) * 127.5, 0, 255).astype(np.uint8)


def load_cleaner(approach: str, device: str):
    if approach == "simple":
        return None, None
    from ai2pixelart.models import resolve_checkpoint, resolve_device
    from ai2pixelart.nninfer import load_checkpoint

    resolved_device = resolve_device(device)
    ckpt = resolve_checkpoint(approach)
    return load_checkpoint(str(ckpt), device=resolved_device), resolved_device


def clean_with_ai2pixelart(img: np.ndarray, approach: str, model, device: str | None, max_colors: int | None):
    if approach == "simple":
        from ai2pixelart.pipeline import clean

        return clean(img, max_colors=max_colors)
    from ai2pixelart.nninfer import nn_clean_image

    return nn_clean_image(img, model, device=device or "cpu", max_colors=max_colors)


def collect_inputs(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return [p for p in sorted(path.glob("*")) if p.suffix.lower() in EXTS]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True, help="Input image or directory")
    parser.add_argument("--output", type=Path, default=Path("outputs/final_pipeline_ai2pixelart"))
    parser.add_argument("--teacher", type=Path, default=Path("models/pixelization.onnx"))
    parser.add_argument("--long-edges", type=int, nargs="+", default=[128, 56, 32])
    parser.add_argument("--teacher-scale", type=int, default=4)
    parser.add_argument("--cleanup", nargs="+", default=["simple", "robust"], choices=["simple", "robust", "detail"])
    parser.add_argument("--device", default="cpu", help="ai2pixelart neural cleanup device: cpu/cuda/auto")
    parser.add_argument("--max-colors", type=int, default=None)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--save-pseudo", action="store_true", help="Also save high-res Wu teacher pseudo-pixel-art")
    args = parser.parse_args()

    files = collect_inputs(args.input)
    if not files:
        raise SystemExit(f"no supported images found in {args.input}")

    sess_options = ort.SessionOptions()
    sess_options.intra_op_num_threads = args.threads
    session = ort.InferenceSession(str(args.teacher), sess_options=sess_options, providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name

    cleaners = {name: load_cleaner(name, args.device) for name in args.cleanup}
    rows = []

    total = len(files) * len(args.long_edges) * len(args.cleanup)
    with tqdm(total=total, desc="pipeline") as pbar:
        for file in files:
            src = Image.open(file).convert("RGB")
            for long_edge in args.long_edges:
                high_w, high_h = aspect_size(*src.size, long_edge * args.teacher_scale, multiple=4)
                teacher_in = src.resize((high_w, high_h), Image.Resampling.BICUBIC)

                t0 = time.perf_counter()
                y = session.run([output_name], {input_name: pil_to_nchw(teacher_in)})[0]
                pseudo = tensor_to_rgb(y)
                teacher_ms = (time.perf_counter() - t0) * 1000.0

                if args.save_pseudo:
                    pseudo_dir = args.output / "pseudo" / str(long_edge)
                    pseudo_dir.mkdir(parents=True, exist_ok=True)
                    Image.fromarray(pseudo).save(pseudo_dir / f"{file.stem}_{long_edge}_pseudo.png")

                for cleanup in args.cleanup:
                    model, cleanup_device = cleaners[cleanup]
                    t1 = time.perf_counter()
                    result = clean_with_ai2pixelart(pseudo, cleanup, model, cleanup_device, args.max_colors)
                    cleaned = clamp_long_edge(Image.fromarray(result.image), long_edge)
                    cleanup_ms = (time.perf_counter() - t1) * 1000.0

                    out_dir = args.output / cleanup / str(long_edge)
                    out_dir.mkdir(parents=True, exist_ok=True)
                    out = out_dir / f"{file.stem}_{long_edge}.png"
                    cleaned.save(out)
                    rows.append({
                        "input": str(file),
                        "output": str(out),
                        "cleanup": cleanup,
                        "long_edge": long_edge,
                        "output_size": list(cleaned.size),
                        "teacher_input_size": [high_w, high_h],
                        "teacher_ms": teacher_ms,
                        "cleanup_ms": cleanup_ms,
                        "palette_size": int(len(result.palette)),
                        "grid": None if result.grid is None else {
                            "pitch_x": float(result.grid.x.pitch),
                            "pitch_y": float(result.grid.y.pitch),
                        },
                    })
                    pbar.update(1)

    report = {
        "input": str(args.input),
        "output": str(args.output),
        "teacher": str(args.teacher),
        "long_edges": args.long_edges,
        "teacher_scale": args.teacher_scale,
        "cleanup": args.cleanup,
        "count": len(rows),
        "rows": rows,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2))
    print(args.output / "report.json")


if __name__ == "__main__":
    main()
