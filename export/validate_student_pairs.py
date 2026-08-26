#!/usr/bin/env python3
"""Validate a student ONNX against precomputed bitmap input/target pairs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image, ImageDraw
from skimage.metrics import peak_signal_noise_ratio, structural_similarity

EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def load_nchw(path: Path) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    arr = np.asarray(img, dtype=np.float32) / 127.5 - 1.0
    return np.transpose(arr, (2, 0, 1))[None]


def tensor_to_rgb(x: np.ndarray) -> np.ndarray:
    arr = np.transpose(x[0], (1, 2, 0))
    return np.clip((arr + 1.0) * 127.5, 0, 255).astype(np.uint8)


def save_compare(path: Path, target: np.ndarray, student: np.ndarray, diff: np.ndarray) -> None:
    h, w = target.shape[:2]
    canvas = Image.new("RGB", (w * 3 + 20, h + 24), "white")
    draw = ImageDraw.Draw(canvas)
    for i, (label, arr) in enumerate((("target", target), ("student", student), ("diff", diff))):
        x = i * (w + 10)
        draw.text((x, 4), label, fill=(0, 0, 0))
        canvas.paste(Image.fromarray(arr), (x, 24))
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", type=Path, required=True)
    parser.add_argument("--student", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/student_pair_validation"))
    parser.add_argument("--report", type=Path, default=Path("outputs/student_pair_validation/report.json"))
    args = parser.parse_args()

    input_dir = args.pairs / "input"
    target_dir = args.pairs / "target"
    files = [p for p in sorted(input_dir.glob("*")) if p.suffix.lower() in EXTS and (target_dir / p.name).exists()]
    if args.limit > 0:
        files = files[: args.limit]
    if not files:
        raise SystemExit(f"no matching pairs under {args.pairs}")

    session = ort.InferenceSession(str(args.student), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name

    rows = []
    for inp_path in files:
        target_path = target_dir / inp_path.name
        x = load_nchw(inp_path)
        s = session.run([output_name], {input_name: x})[0]
        s_rgb = tensor_to_rgb(s)
        t_rgb = np.asarray(Image.open(target_path).convert("RGB"), dtype=np.uint8)
        if s_rgb.shape != t_rgb.shape:
            Image.fromarray(s_rgb).resize((t_rgb.shape[1], t_rgb.shape[0]), Image.Resampling.BICUBIC)
        diff = np.abs(t_rgb.astype(np.int16) - s_rgb.astype(np.int16)).astype(np.uint8)
        row = {
            "image": inp_path.name,
            "psnr": float(peak_signal_noise_ratio(t_rgb, s_rgb, data_range=255)),
            "ssim": float(structural_similarity(t_rgb, s_rgb, channel_axis=2, data_range=255)),
            "mean_abs_error_rgb": float(diff.mean()),
            "max_abs_error_rgb": int(diff.max()),
        }
        rows.append(row)
        save_compare(args.output_dir / inp_path.name, t_rgb, s_rgb, diff)
        print(f"{inp_path.name}: PSNR={row['psnr']:.2f} SSIM={row['ssim']:.4f} MAE={row['mean_abs_error_rgb']:.2f}")

    report = {
        "count": len(rows),
        "pairs": str(args.pairs),
        "student": str(args.student),
        "mean_psnr": float(np.mean([r["psnr"] for r in rows])),
        "mean_ssim": float(np.mean([r["ssim"] for r in rows])),
        "mean_abs_error_rgb": float(np.mean([r["mean_abs_error_rgb"] for r in rows])),
        "max_abs_error_rgb": int(max(r["max_abs_error_rgb"] for r in rows)),
        "images": rows,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
