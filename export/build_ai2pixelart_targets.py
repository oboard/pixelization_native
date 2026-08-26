#!/usr/bin/env python3
"""Build paired bitmap targets using WuZongWei6 teacher + ai2pixelart cleanup.

For each source image:
  1. Resize source to teacher long-edge = target_long_edge * teacher_scale.
  2. Run the current FP32 ONNX Pixelization teacher at that high resolution.
  3. Clean the pseudo-pixel-art teacher output with ai2pixelart.
  4. Save the cleaned true-resolution bitmap as target.
  5. Resize the original source to the cleaned target size as student input.

This produces paired data where every output file pixel is a logical pixel.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image
from tqdm import tqdm

EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def aspect_size(w: int, h: int, long_edge: int) -> tuple[int, int]:
    if w >= h:
        short = max(4, round((h * long_edge / w) / 4) * 4)
        return long_edge, short
    short = max(4, round((w * long_edge / h) / 4) * 4)
    return short, long_edge


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

        result = clean(img, max_colors=max_colors)
    else:
        from ai2pixelart.nninfer import nn_clean_image

        result = nn_clean_image(img, model, device=device or "cpu", max_colors=max_colors)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--teacher", type=Path, default=Path("models/pixelization.onnx"))
    parser.add_argument("--output", type=Path, default=Path("data/ai2pixelart_targets/train"))
    parser.add_argument("--long-edge", type=int, default=128)
    parser.add_argument("--teacher-scale", type=int, default=4)
    parser.add_argument("--approach", default="robust", choices=["simple", "robust", "detail"])
    parser.add_argument("--device", default="cpu", help="ai2pixelart neural device; cpu/cuda/auto")
    parser.add_argument("--max-colors", type=int, default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.long_edge % 4 != 0:
        raise SystemExit("--long-edge must be divisible by 4")

    files = [p for p in sorted(args.images.rglob("*")) if p.suffix.lower() in EXTS]
    if args.limit > 0:
        files = files[: args.limit]
    if not files:
        raise SystemExit(f"no images found in {args.images}")

    input_dir = args.output / "input"
    target_dir = args.output / "target"
    teacher_dir = args.output / "teacher_pseudo"
    for d in (input_dir, target_dir, teacher_dir):
        d.mkdir(parents=True, exist_ok=True)

    sess = ort.InferenceSession(str(args.teacher), sess_options=ort.SessionOptions(), providers=["CPUExecutionProvider"])
    sess.set_providers(["CPUExecutionProvider"], [{"intra_op_num_threads": args.threads}])
    input_name = sess.get_inputs()[0].name
    output_name = sess.get_outputs()[0].name
    cleaner, cleaner_device = load_cleaner(args.approach, args.device)

    rows = []
    for src in tqdm(files, desc="targets"):
        out_input = input_dir / f"{src.stem}.png"
        out_target = target_dir / f"{src.stem}.png"
        out_teacher = teacher_dir / f"{src.stem}.png"
        if out_input.exists() and out_target.exists() and not args.force:
            continue

        img = Image.open(src).convert("RGB")
        low_w, low_h = aspect_size(*img.size, args.long_edge)
        high = img.resize((low_w * args.teacher_scale, low_h * args.teacher_scale), Image.Resampling.BICUBIC)
        y = sess.run([output_name], {input_name: pil_to_nchw(high)})[0]
        pseudo = tensor_to_rgb(y)
        Image.fromarray(pseudo).save(out_teacher)

        cleaned = clean_with_ai2pixelart(pseudo, args.approach, cleaner, cleaner_device, args.max_colors)
        target = Image.fromarray(cleaned.image)
        # ai2pixelart derives the grid's true resolution. If it detects a finer
        # grid than our requested product size, keep bitmap semantics but clamp
        # the long edge back to the requested target with NEAREST.
        tw, th = target.size
        if max(tw, th) > args.long_edge:
            tw, th = aspect_size(tw, th, args.long_edge)
            target = target.resize((tw, th), Image.Resampling.NEAREST)
        # Use the final bitmap target shape for the paired student input so
        # input and target have identical H/W.
        inp = img.resize((tw, th), Image.Resampling.BICUBIC)
        inp.save(out_input)
        target.save(out_target)
        rows.append({
            "source": str(src),
            "input": str(out_input),
            "target": str(out_target),
            "teacher_pseudo": str(out_teacher),
            "target_size": [tw, th],
            "palette_size": int(len(cleaned.palette)),
            "grid": None if cleaned.grid is None else {
                "pitch_x": float(cleaned.grid.x.pitch),
                "pitch_y": float(cleaned.grid.y.pitch),
            },
        })

    manifest = {
        "source": str(args.images),
        "teacher": str(args.teacher),
        "output": str(args.output),
        "long_edge": args.long_edge,
        "teacher_scale": args.teacher_scale,
        "approach": args.approach,
        "count_written_or_seen": len(list(target_dir.glob("*.png"))),
        "new_rows": rows,
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({k: v for k, v in manifest.items() if k != "new_rows"}, indent=2))


if __name__ == "__main__":
    main()
