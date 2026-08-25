#!/usr/bin/env python3
"""
Full parity validation: PyTorch vs Rust with identical preprocessing.
"""
import subprocess
import numpy as np
from PIL import Image
from pathlib import Path
from skimage.metrics import peak_signal_noise_ratio as psnr
from skimage.metrics import structural_similarity as ssim
import torch
import sys

sys.path.insert(0, str(Path(__file__).parent))
from model import TestProInference


def rescale(img: Image.Image) -> Image.Image:
    """Match upstream rescale() logic."""
    w, h = img.size
    while w > 4000 or h > 4000:
        img = img.resize((w // 2, h // 2), Image.BICUBIC)
        w, h = img.size
    while w < 128 or h < 128:
        img = img.resize((w * 2, h * 2), Image.BICUBIC)
        w, h = img.size
    return img


def preprocess_pytorch_full(img_path: str, cell_size: int = 4):
    """Full preprocessing matching upstream test_pro.py"""
    # Step 1: Load and rescale
    img = Image.open(img_path).convert("RGB")
    img = rescale(img)
    w, h = img.size
    
    # Step 2: Resize to (W//cell_size)*4 × (H//cell_size)*4
    best_cell_size = 4
    target_w = (w // cell_size) * best_cell_size
    target_h = (h // cell_size) * best_cell_size
    img = img.resize((target_w, target_h), Image.BICUBIC)
    w, h = img.size
    
    # Step 3: Center-crop to multiple of 4
    nw = (w // 4) * 4
    nh = (h // 4) * 4
    left = (w - nw) // 2
    top = (h - nh) // 2
    img = img.crop((left, top, left + nw, top + nh))
    
    return img


def run_pytorch_full(model, img_path: str, cell_size: int = 4):
    """Run PyTorch inference with full preprocessing."""
    img = preprocess_pytorch_full(img_path, cell_size)
    
    # Normalize
    import torchvision.transforms as transforms
    trans = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
    ])
    tensor = trans(img)[None, :, :, :]
    
    # Inference
    with torch.no_grad():
        output = model(tensor)
    
    # Denormalize
    out_img = output[0].cpu().float().numpy()
    out_img = (np.transpose(out_img, (1, 2, 0)) + 1) / 2.0 * 255.0
    out_img = out_img.astype(np.uint8)
    out_img = Image.fromarray(out_img)
    
    # Postprocess: nearest /4 then *cell_size
    best_cell_size = 4
    out_img = out_img.resize(
        (out_img.size[0] // best_cell_size, out_img.size[1] // best_cell_size),
        Image.NEAREST
    )
    out_img = out_img.resize(
        (out_img.size[0] * cell_size, out_img.size[1] * cell_size),
        Image.NEAREST
    )
    
    return np.array(out_img)


def run_rust(model_path: str, img_path: str, cell_size: int = 4, threads: int = 4):
    """Run Rust CLI inference."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "output.png"
        cmd = [
            "cargo", "run", "--release", "-p", "pixelization-cli", "--",
            "--model", model_path,
            "--cell-size", str(cell_size),
            "--threads", str(threads),
            img_path,
            str(output_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Rust inference failed: {result.stderr}")
        return np.array(Image.open(output_path).convert("RGB"))


def compare_images(img1: np.ndarray, img2: np.ndarray, name1: str, name2: str):
    """Compare two images with metrics."""
    if img1.shape != img2.shape:
        print(f"  Size mismatch: {img1.shape} vs {img2.shape}")
        # Resize for comparison
        img2 = np.array(Image.fromarray(img2).resize((img1.shape[1], img1.shape[0]), Image.NEAREST))
    
    p = psnr(img1, img2, data_range=255)
    s = ssim(img1, img2, data_range=255, channel_axis=2)
    
    diff = np.abs(img1.astype(np.float32) - img2.astype(np.float32))
    max_err = diff.max()
    mean_err = diff.mean()
    
    print(f"  {name1} vs {name2}:")
    print(f"    PSNR: {p:.2f} dB")
    print(f"    SSIM: {s:.6f}")
    print(f"    Max error: {max_err:.2f}")
    print(f"    Mean error: {mean_err:.4f}")
    
    return {"psnr": p, "ssim": s, "max_err": max_err, "mean_err": mean_err}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Full PyTorch vs Rust parity")
    parser.add_argument("--generator", type=Path, required=True, help="160_net_G_A.pth")
    parser.add_argument("--alias", type=Path, required=True, help="alias_net.pth")
    parser.add_argument("--rust-model", type=Path, required=True, help="ONNX model for Rust")
    parser.add_argument("--images", nargs="+", default=["test_images/test_1.png"])
    parser.add_argument("--cell-size", type=int, default=4)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    
    print("Loading PyTorch model...")
    model = TestProInference(args.generator, args.alias).eval()
    
    results = []
    for img_path in args.images:
        print(f"\nProcessing {img_path}...")
        
        # PyTorch
        print("  Running PyTorch...")
        pytorch_output = run_pytorch_full(model, img_path, args.cell_size)
        print(f"    PyTorch output: {pytorch_output.shape}")
        
        # Rust
        print("  Running Rust...")
        rust_output = run_rust(str(args.rust_model), img_path, args.cell_size, args.threads)
        print(f"    Rust output: {rust_output.shape}")
        
        # Compare
        metrics = compare_images(pytorch_output, rust_output, "PyTorch", "Rust")
        results.append({"image": img_path, **metrics})
        
        # Save outputs for visual inspection
        Image.fromarray(pytorch_output).save(img_path.replace(".png", "_pytorch_full.png"))
        Image.fromarray(rust_output).save(img_path.replace(".png", "_rust_full.png"))
    
    print("\n" + "=" * 60)
    print("Summary:")
    print(f"  Mean PSNR: {np.mean([r['psnr'] for r in results]):.2f} dB")
    print(f"  Mean SSIM: {np.mean([r['ssim'] for r in results]):.6f}")
    print(f"  Max error: {max(r['max_err'] for r in results):.2f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
