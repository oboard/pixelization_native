#!/usr/bin/env python3
"""Export a dynamic-shape Test Pro ONNX graph (opset 17+).

The network can accept any input size divisible by 4, matching upstream test_pro.py.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import torch
from model import TestProInference


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generator", type=Path, required=True, help="160_net_G_A.pth")
    parser.add_argument("--alias", type=Path, required=True, help="alias_net.pth")
    parser.add_argument("--output", type=Path, default=Path("models/pixelization.onnx"))
    parser.add_argument("--size", type=int, default=512, help="Example size for tracing (must be divisible by 4)")
    parser.add_argument("--static", action="store_true", help="Export static shape instead of dynamic")
    args = parser.parse_args()
    
    if args.size % 4 != 0:
        raise SystemExit(f"--size must be divisible by 4, got {args.size}")
    
    model = TestProInference(args.generator, args.alias).eval()
    example = torch.zeros((1, 3, args.size, args.size), dtype=torch.float32)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    
    if args.static:
        # Static shape export (original behavior)
        with torch.inference_mode():
            torch.onnx.export(
                model, (example,), args.output, 
                input_names=["image"], 
                output_names=["pixelized"],
                opset_version=17, 
                dynamo=False, 
                do_constant_folding=True,
            )
    else:
        # Dynamic shape export (matches upstream behavior)
        with torch.inference_mode():
            torch.onnx.export(
                model, (example,), args.output, 
                input_names=["image"], 
                output_names=["pixelized"],
                opset_version=17, 
                dynamo=False, 
                do_constant_folding=True,
                dynamic_axes={
                    "image": {0: "batch", 2: "height", 3: "width"},
                    "pixelized": {0: "batch", 2: "height", 3: "width"},
                },
            )
    print(args.output)


if __name__ == "__main__":
    main()
