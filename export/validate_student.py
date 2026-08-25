#!/usr/bin/env python3
"""Validate a low-resolution student against the FP32 teacher.

Compares teacher PyTorch outputs with student ONNX Runtime outputs at a fixed
<=128 resolution and saves visual samples for manual inspection.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image, ImageDraw
from skimage.metrics import peak_signal_noise_ratio, structural_similarity
import torch
import torchvision.transforms.functional as TF

from model import TestProInference

EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def preprocess(path: Path, resolution: int) -> torch.Tensor:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    side = min(w, h)
    left = max(0, (w - side) // 2)
    top = max(0, (h - side) // 2)
    img = img.crop((left, top, left + side, top + side))
    img = img.resize((resolution, resolution), Image.Resampling.BICUBIC)
    return (TF.to_tensor(img) * 2.0 - 1.0).unsqueeze(0)


def tensor_to_rgb(x: np.ndarray) -> np.ndarray:
    if x.shape[0] != 1:
        raise ValueError(f"expected batch=1, got {x.shape}")
    img = (np.transpose(x[0], (1, 2, 0)) + 1.0) * 127.5
    return np.clip(img, 0, 255).astype(np.uint8)


def save_compare(path: Path, teacher: np.ndarray, student: np.ndarray, diff: np.ndarray) -> None:
    h, w = teacher.shape[:2]
    canvas = Image.new("RGB", (w * 3 + 20, h + 24), "white")
    draw = ImageDraw.Draw(canvas)
    for i, (label, arr) in enumerate((("teacher", teacher), ("student", student), ("diff", diff))):
        x = i * (w + 10)
        draw.text((x, 4), label, fill=(0, 0, 0))
        canvas.paste(Image.fromarray(arr), (x, 24))
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--generator", type=Path, default=Path("checkpoints/160_net_G_A.pth"))
    parser.add_argument("--alias", type=Path, default=Path("alias_net.pth"))
    parser.add_argument("--student", type=Path, required=True, help="Student ONNX model")
    parser.add_argument("--resolution", type=int, default=128)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/student_validation"))
    parser.add_argument("--report", type=Path, default=Path("outputs/student_validation/report.json"))
    args = parser.parse_args()

    if args.resolution % 4 != 0 or args.resolution > 128:
        raise SystemExit("--resolution must be divisible by 4 and <=128")

    files = [p for p in sorted(args.images.rglob("*")) if p.suffix.lower() in EXTS][: args.limit]
    if not files:
        raise SystemExit(f"no images found in {args.images}")

    teacher = TestProInference(args.generator, args.alias).eval()
    session = ort.InferenceSession(str(args.student), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name

    rows = []
    with torch.inference_mode():
        for file in files:
            x = preprocess(file, args.resolution)
            t = teacher(x).cpu().numpy()
            s = session.run([output_name], {input_name: x.numpy()})[0]
            t_rgb = tensor_to_rgb(t)
            s_rgb = tensor_to_rgb(s)
            abs_diff = np.abs(t_rgb.astype(np.int16) - s_rgb.astype(np.int16)).astype(np.uint8)
            metric_diff = np.abs(t.astype(np.float32) - s.astype(np.float32))
            row = {
                "image": str(file),
                "psnr": float(peak_signal_noise_ratio(t_rgb, s_rgb, data_range=255)),
                "ssim": float(structural_similarity(t_rgb, s_rgb, channel_axis=2, data_range=255)),
                "max_abs_error": float(metric_diff.max()),
                "mean_abs_error": float(metric_diff.mean()),
            }
            rows.append(row)
            save_compare(args.output_dir / f"{file.stem}_{args.resolution}.png", t_rgb, s_rgb, abs_diff)
            print(f"{file.name}: PSNR={row['psnr']:.2f} SSIM={row['ssim']:.4f} max={row['max_abs_error']:.4f} mean={row['mean_abs_error']:.4f}")

    report = {
        "count": len(rows),
        "student": str(args.student),
        "resolution": args.resolution,
        "mean_psnr": float(np.mean([r["psnr"] for r in rows])),
        "mean_ssim": float(np.mean([r["ssim"] for r in rows])),
        "max_abs_error": float(max(r["max_abs_error"] for r in rows)),
        "mean_abs_error": float(np.mean([r["mean_abs_error"] for r in rows])),
        "images": rows,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
