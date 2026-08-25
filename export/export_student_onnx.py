#!/usr/bin/env python3
"""Export the small student Pixelization model to ONNX.

This exports an untrained or trained student checkpoint. Training is handled by
train_student.py. The default architecture is designed to remain <10MB FP32.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import torch

from student_model import PixelizationStudent, count_parameters


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, default=None, help="Optional student .pth checkpoint")
    parser.add_argument("--output", type=Path, default=Path("models/pixelization_student.onnx"))
    parser.add_argument("--width", type=int, default=32)
    parser.add_argument("--blocks", type=int, default=4)
    parser.add_argument("--size", type=int, default=128, help="Example trace size; must be divisible by 4")
    args = parser.parse_args()

    if args.size % 4 != 0:
        raise SystemExit(f"--size must be divisible by 4, got {args.size}")

    model = PixelizationStudent(width=args.width, blocks=args.blocks).eval()
    if args.checkpoint is not None:
        state = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
        if "model" in state:
            state = state["model"]
        model.load_state_dict(state, strict=True)

    params = count_parameters(model)
    print(f"student params: {params:,} ({params * 4 / 1024 / 1024:.2f} MiB raw FP32)")
    if params * 4 >= 10 * 1024 * 1024:
        raise SystemExit("student parameter payload is >=10MB; reduce --width/--blocks")

    example = torch.zeros((1, 3, args.size, args.size), dtype=torch.float32)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with torch.inference_mode():
        torch.onnx.export(
            model,
            (example,),
            args.output,
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
