#!/usr/bin/env python3
"""Compare Rust output vs ONNX output."""
import subprocess
import numpy as np
from PIL import Image
from pathlib import Path
from skimage.metrics import peak_signal_noise_ratio as psnr
from skimage.metrics import structural_similarity as ssim
import onnxruntime as ort
import tempfile
import shutil


def preprocess_onnx(img_path: str, size: int = 512):
    """Preprocess image for ONNX inference."""
    image = Image.open(img_path).convert("RGB").resize((size, size), Image.Resampling.BICUBIC)
    arr = np.transpose(np.asarray(image, dtype=np.float32) / 127.5 - 1.0, (2, 0, 1))[None]
    return arr


def postprocess_onnx(output: np.ndarray) -> np.ndarray:
    """Convert ONNX output to RGB image."""
    rgb = np.transpose((np.clip((output[0] + 1) * 127.5, 0, 255)).astype(np.uint8), (1, 2, 0))
    return rgb


def run_rust(model_path: str, input_path: str, output_path: str, cell_size: int = 4, threads: int = 4):
    """Run Rust CLI inference."""
    cmd = [
        "cargo", "run", "--release", "-p", "pixelization-cli", "--",
        "--model", model_path,
        "--cell-size", str(cell_size),
        "--threads", str(threads),
        input_path,
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Rust inference failed: {result.stderr}")
    return output_path


def run_onnx(onnx_path: str, img_path: str):
    """Run ONNX inference."""
    session = ort.InferenceSession(onnx_path, providers=['CPUExecutionProvider'])
    inp = preprocess_onnx(img_path)
    output = session.run(["pixelized"], {"image": inp})[0]
    return postprocess_onnx(output)


def compare_images(img1: np.ndarray, img2: np.ndarray, name1: str, name2: str):
    """Compare two images with metrics."""
    if img1.shape != img2.shape:
        print(f"  Size mismatch: {img1.shape} vs {img2.shape}")
        # Resize to match
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
    parser = argparse.ArgumentParser(description="Rust vs ONNX comparison")
    parser.add_argument("--model", default="models/pixelization.onnx", help="ONNX model path")
    parser.add_argument("--images", nargs="+", default=["test_images/test_1.png"], help="Test images")
    parser.add_argument("--cell-size", type=int, default=4)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    
    results = []
    
    for img_path in args.images:
        print(f"\nProcessing {img_path}...")
        
        # Run Rust inference
        with tempfile.TemporaryDirectory() as tmpdir:
            rust_output = Path(tmpdir) / "rust_output.png"
            run_rust(args.model, img_path, str(rust_output), args.cell_size, args.threads)
            rust_img = np.array(Image.open(rust_output).convert("RGB"))
        
        # Run ONNX inference (on 512x512 resized input)
        onnx_img = run_onnx(args.model, img_path)
        
        # Note: Rust uses full preprocessing pipeline with rescale/resize/crop,
        # while simple ONNX test just resizes to 512x512. So we expect differences.
        print(f"  Rust output shape: {rust_img.shape}")
        print(f"  ONNX output shape: {onnx_img.shape}")
        
        # Save ONNX output for comparison
        onnx_output_path = img_path.replace(".png", "_onnx_simple.png")
        Image.fromarray(onnx_img).save(onnx_output_path)
        print(f"  Saved ONNX output to {onnx_output_path}")
        
        # For fair comparison, we need to run Rust on 512x512 input too
        with tempfile.TemporaryDirectory() as tmpdir:
            # Resize input to 512x512 first
            resized_input = Path(tmpdir) / "resized_input.png"
            Image.open(img_path).convert("RGB").resize((512, 512), Image.BICUBIC).save(resized_input)
            
            rust_output_512 = Path(tmpdir) / "rust_output_512.png"
            run_rust(args.model, str(resized_input), str(rust_output_512), args.cell_size, args.threads)
            rust_img_512 = np.array(Image.open(rust_output_512).convert("RGB"))
        
        # Now compare
        metrics = compare_images(rust_img_512, onnx_img, "Rust", "ONNX")
        results.append({"image": img_path, **metrics})
    
    print("\n" + "=" * 60)
    print("Summary:")
    print(f"  Mean PSNR: {np.mean([r['psnr'] for r in results]):.2f} dB")
    print(f"  Mean SSIM: {np.mean([r['ssim'] for r in results]):.6f}")
    print(f"  Max error: {max(r['max_err'] for r in results):.2f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
