#!/usr/bin/env python3
"""Measure PyTorch-vs-ONNX Runtime tensor parity and save visual diffs."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
from PIL import Image
import torch
import onnxruntime as ort
from skimage.metrics import structural_similarity
from model import TestProInference


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = np.mean((a - b) ** 2)
    return float("inf") if mse == 0 else float(20 * np.log10(2.0 / np.sqrt(mse)))

def preprocess(path: Path, size: int) -> np.ndarray:
    image = Image.open(path).convert("RGB").resize((size, size), Image.Resampling.BICUBIC)
    return np.transpose(np.asarray(image, dtype=np.float32) / 127.5 - 1.0, (2, 0, 1))[None]

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--generator", type=Path, required=True); p.add_argument("--alias", type=Path, required=True)
    p.add_argument("--onnx", type=Path, default=Path("models/pixelization.onnx")); p.add_argument("--images", type=Path, required=True)
    p.add_argument("--report", type=Path, default=Path("models/parity-report.json")); p.add_argument("--diff-dir", type=Path, default=Path("models/parity-diff"))
    args = p.parse_args(); files = [f for f in sorted(args.images.rglob("*")) if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
    if len(files) < 20: raise SystemExit(f"need at least 20 images; found {len(files)}")
    model = TestProInference(args.generator, args.alias).eval(); session = ort.InferenceSession(str(args.onnx), providers=["CPUExecutionProvider"])
    args.diff_dir.mkdir(parents=True, exist_ok=True); rows = []
    for file in files:
        inp = preprocess(file, 512)
        with torch.inference_mode(): pt = model(torch.from_numpy(inp)).numpy()
        ox = session.run(["pixelized"], {"image": inp})[0]
        delta = np.abs(pt - ox); pt_rgb = np.transpose((np.clip((pt[0] + 1) * 127.5, 0, 255)).astype(np.uint8), (1,2,0)); ox_rgb = np.transpose((np.clip((ox[0] + 1) * 127.5, 0, 255)).astype(np.uint8), (1,2,0))
        Image.fromarray(np.abs(pt_rgb.astype(np.int16) - ox_rgb.astype(np.int16)).astype(np.uint8)).save(args.diff_dir / f"{file.stem}.png")
        rows.append({"image": str(file), "max_abs_error": float(delta.max()), "mean_abs_error": float(delta.mean()), "psnr": psnr(pt, ox), "ssim": float(structural_similarity(pt_rgb, ox_rgb, channel_axis=2, data_range=255))})
    report = {"count": len(rows), "max_abs_error": max(r["max_abs_error"] for r in rows), "mean_abs_error": float(np.mean([r["mean_abs_error"] for r in rows])), "mean_psnr": float(np.mean([r["psnr"] for r in rows])), "mean_ssim": float(np.mean([r["ssim"] for r in rows])), "images": rows}
    args.report.parent.mkdir(parents=True, exist_ok=True); args.report.write_text(json.dumps(report, indent=2)); print(json.dumps(report, indent=2))

if __name__ == "__main__": main()
