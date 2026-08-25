#!/usr/bin/env python3
"""Quick parity test with fewer images."""
from __future__ import annotations
import argparse
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
    p.add_argument("--generator", type=Path, required=True)
    p.add_argument("--alias", type=Path, required=True)
    p.add_argument("--onnx", type=Path, default=Path("models/pixelization.onnx"))
    p.add_argument("--images", type=Path, required=True)
    p.add_argument("--count", type=int, default=5, help="Number of images to test")
    args = p.parse_args()
    
    files = [f for f in sorted(args.images.rglob("*")) if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
    files = files[:args.count]
    
    print(f"Loading PyTorch model...")
    model = TestProInference(args.generator, args.alias).eval()
    print(f"Loading ONNX model...")
    session = ort.InferenceSession(str(args.onnx), providers=["CPUExecutionProvider"])
    
    print(f"Testing {len(files)} images...")
    results = []
    
    for i, file in enumerate(files):
        print(f"  [{i+1}/{len(files)}] {file.name}...", end=" ", flush=True)
        inp = preprocess(file, 512)
        
        with torch.inference_mode():
            pt = model(torch.from_numpy(inp)).numpy()
        
        ox = session.run(["pixelized"], {"image": inp})[0]
        
        delta = np.abs(pt - ox)
        pt_rgb = np.transpose((np.clip((pt[0] + 1) * 127.5, 0, 255)).astype(np.uint8), (1, 2, 0))
        ox_rgb = np.transpose((np.clip((ox[0] + 1) * 127.5, 0, 255)).astype(np.uint8), (1, 2, 0))
        
        p = psnr(pt, ox)
        s = float(structural_similarity(pt_rgb, ox_rgb, channel_axis=2, data_range=255))
        
        print(f"PSNR={p:.2f}dB SSIM={s:.6f} max_err={delta.max():.4f}")
        results.append({"file": file.name, "psnr": p, "ssim": s, "max_err": float(delta.max())})
    
    print("\n" + "=" * 60)
    print("Summary:")
    print(f"  Mean PSNR: {np.mean([r['psnr'] for r in results]):.2f} dB")
    print(f"  Mean SSIM: {np.mean([r['ssim'] for r in results]):.6f}")
    print(f"  Max error: {max(r['max_err'] for r in results):.4f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
