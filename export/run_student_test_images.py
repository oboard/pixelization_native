#!/usr/bin/env python3
"""Run a student ONNX model on test images and save <=128px pixel-art outputs.

This mirrors the low-resolution deployment geometry: center-crop square, bicubic
resize to target resolution, ONNX inference, nearest-neighbor /4 then x4.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image

EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def aspect_size(w: int, h: int, long_edge: int) -> tuple[int, int]:
    if w >= h:
        short = max(4, round((h * long_edge / w) / 4) * 4)
        return long_edge, short
    short = max(4, round((w * long_edge / h) / 4) * 4)
    return short, long_edge


def preprocess(path: Path, long_edge: int) -> tuple[np.ndarray, tuple[int, int]]:
    img = Image.open(path).convert("RGB")
    tw, th = aspect_size(*img.size, long_edge)
    img = img.resize((tw, th), Image.Resampling.BICUBIC)
    arr = np.asarray(img, dtype=np.float32) / 127.5 - 1.0
    return np.transpose(arr, (2, 0, 1))[None], (tw, th)


def postprocess(out: np.ndarray, size: tuple[int, int], palette_colors: int = 0) -> Image.Image:
    # Bitmap mode: model output pixels are the final pixels. Do NOT collapse to
    # target/4 and upscale back; that creates 4×4 "large pixels" instead of a
    # true low-resolution bitmap.
    arr = np.transpose(out[0], (1, 2, 0))
    arr = np.clip((arr + 1.0) * 127.5, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)
    if palette_colors > 0:
        img = img.quantize(colors=palette_colors, method=Image.Quantize.MEDIANCUT).convert("RGB")
    return img


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/student_test"))
    parser.add_argument("--long-edges", type=int, nargs="+", default=[128, 56, 32])
    parser.add_argument("--resolutions", type=int, nargs="+", default=None, help="Deprecated alias for --long-edges")
    parser.add_argument("--palette-colors", type=int, default=0, help="Optional per-image color quantization; 0 disables it")
    parser.add_argument("--preview-scale", type=int, default=1, help="Optional nearest-neighbor preview upscale factor")
    args = parser.parse_args()

    files = [p for p in sorted(args.images.glob("*")) if p.suffix.lower() in EXTS]
    if not files:
        raise SystemExit(f"no supported images in {args.images}")

    session = ort.InferenceSession(str(args.model), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name

    long_edges = args.resolutions if args.resolutions is not None else args.long_edges
    for res in long_edges:
        if res % 4 != 0:
            raise SystemExit(f"long edge must be divisible by 4: {res}")
        out_dir = args.output_dir / str(res)
        out_dir.mkdir(parents=True, exist_ok=True)
        for file in files:
            x, size = preprocess(file, res)
            y = session.run([output_name], {input_name: x})[0]
            img = postprocess(y, size, args.palette_colors)
            out = out_dir / f"{file.stem}_{res}.png"
            img.save(out)
            print(out)
            if args.preview_scale > 1:
                preview_dir = args.output_dir / f"{res}_preview_x{args.preview_scale}"
                preview_dir.mkdir(parents=True, exist_ok=True)
                preview = img.resize((img.width * args.preview_scale, img.height * args.preview_scale), Image.Resampling.NEAREST)
                preview_out = preview_dir / f"{file.stem}_{res}_preview_x{args.preview_scale}.png"
                preview.save(preview_out)
                print(preview_out)


if __name__ == "__main__":
    main()
