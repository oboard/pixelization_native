#!/usr/bin/env python3
"""Distill a <10MB low-resolution student from the upstream-exact teacher.

The teacher is the current FP32 Pixelization graph restored in export/model.py.
This script trains only the student. It does not modify upstream weights.

Typical use:
  uv run python export/train_student.py \
    --images /path/to/training/images \
    --generator checkpoints/160_net_G_A.pth \
    --alias alias_net.pth \
    --output checkpoints/student_lowres.pth \
    --resolution 128 \
    --steps 20000
"""
from __future__ import annotations

import argparse
import random
from pathlib import Path

import numpy as np
from PIL import Image
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset
import torchvision.transforms.functional as TF

from model import TestProInference
from student_model import PixelizationStudent, count_parameters


EXTS = {".png", ".jpg", ".jpeg", ".webp"}


class ImageFolderDataset(Dataset):
    def __init__(self, root: Path, resolution: int) -> None:
        self.files = [p for p in sorted(root.rglob("*")) if p.suffix.lower() in EXTS]
        if not self.files:
            raise SystemExit(f"no images found in {root}")
        self.resolution = resolution

    def __len__(self) -> int:
        return len(self.files)

    def __getitem__(self, idx: int) -> torch.Tensor:
        path = self.files[idx % len(self.files)]
        img = Image.open(path).convert("RGB")
        # Random square crop before resizing for augmentation.
        w, h = img.size
        side = min(w, h)
        if side > 0:
            if w != h:
                left = random.randint(0, max(0, w - side))
                top = random.randint(0, max(0, h - side))
                img = img.crop((left, top, left + side, top + side))
        img = img.resize((self.resolution, self.resolution), Image.Resampling.BICUBIC)
        x = TF.to_tensor(img) * 2.0 - 1.0
        return x


def tv_loss(x: torch.Tensor) -> torch.Tensor:
    return (x[:, :, 1:, :] - x[:, :, :-1, :]).abs().mean() + (x[:, :, :, 1:] - x[:, :, :, :-1]).abs().mean()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--generator", type=Path, default=Path("checkpoints/160_net_G_A.pth"))
    parser.add_argument("--alias", type=Path, default=Path("alias_net.pth"))
    parser.add_argument("--output", type=Path, default=Path("checkpoints/student_lowres.pth"))
    parser.add_argument("--resolution", type=int, default=128)
    parser.add_argument("--width", type=int, default=32)
    parser.add_argument("--blocks", type=int, default=4)
    # Teacher export graph is batch-1 faithful because upstream modulation uses groups=batch.
    # Keep default batch size 1 unless the teacher is reworked for true dynamic batching.
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--steps", type=int, default=20000)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--device", default="mps" if torch.backends.mps.is_available() else "cpu")
    parser.add_argument("--save-every", type=int, default=1000)
    args = parser.parse_args()

    if args.resolution % 4 != 0 or args.resolution > 128:
        raise SystemExit("--resolution must be divisible by 4 and <=128")

    device = torch.device(args.device)
    dataset = ImageFolderDataset(args.images, args.resolution)
    loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=True, num_workers=0, drop_last=True)
    it = iter(loader)

    teacher = TestProInference(args.generator, args.alias).eval().to(device)
    for p in teacher.parameters():
        p.requires_grad_(False)

    student = PixelizationStudent(width=args.width, blocks=args.blocks).train().to(device)
    params = count_parameters(student)
    print(f"student params: {params:,} ({params * 4 / 1024 / 1024:.2f} MiB raw FP32)")
    if params * 4 >= 10 * 1024 * 1024:
        raise SystemExit("student parameter payload is >=10MB; reduce width/blocks")

    opt = torch.optim.AdamW(student.parameters(), lr=args.lr, betas=(0.9, 0.99), weight_decay=1e-4)
    l1 = nn.L1Loss()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    for step in range(1, args.steps + 1):
        try:
            x = next(it)
        except StopIteration:
            it = iter(loader)
            x = next(it)
        x = x.to(device)

        with torch.no_grad():
            y = teacher(x).detach()
        pred = student(x)
        loss = l1(pred, y) + 0.02 * tv_loss(pred - y)

        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()

        if step == 1 or step % 50 == 0:
            print(f"step={step} loss={loss.item():.6f}")
        if step % args.save_every == 0 or step == args.steps:
            torch.save({
                "model": student.state_dict(),
                "width": args.width,
                "blocks": args.blocks,
                "resolution": args.resolution,
                "step": step,
                "params": params,
            }, args.output)
            print(f"saved {args.output}")


if __name__ == "__main__":
    main()
