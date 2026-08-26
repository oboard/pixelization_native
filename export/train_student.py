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


def aspect_size(w: int, h: int, long_edge: int) -> tuple[int, int]:
    if w >= h:
        short = max(4, round((h * long_edge / w) / 4) * 4)
        return long_edge, short
    short = max(4, round((w * long_edge / h) / 4) * 4)
    return short, long_edge


class ImageFolderDataset(Dataset):
    def __init__(self, root: Path, long_edge: int, *, resample: Image.Resampling = Image.Resampling.BICUBIC) -> None:
        self.files = [p for p in sorted(root.rglob("*")) if p.suffix.lower() in EXTS]
        if not self.files:
            raise SystemExit(f"no images found in {root}")
        self.long_edge = long_edge
        self.resample = resample

    def __len__(self) -> int:
        return len(self.files)

    def __getitem__(self, idx: int) -> torch.Tensor:
        path = self.files[idx % len(self.files)]
        img = Image.open(path).convert("RGB")
        w, h = img.size
        tw, th = aspect_size(w, h, self.long_edge)
        img = img.resize((tw, th), self.resample)
        x = TF.to_tensor(img) * 2.0 - 1.0
        return x


class BitmapDistillDataset(Dataset):
    """Return low-res student input and high-res teacher input for bitmap targets.

    For final bitmap long_edge=128, the teacher is run at 4× long edge and then
    nearest-downsampled to 128. This makes one output file pixel correspond to one
    logical pixel instead of making each logical pixel a 4×4 block.
    """

    def __init__(self, root: Path, long_edge: int, teacher_scale: int = 4) -> None:
        self.files = [p for p in sorted(root.rglob("*")) if p.suffix.lower() in EXTS]
        if not self.files:
            raise SystemExit(f"no images found in {root}")
        self.long_edge = long_edge
        self.teacher_scale = teacher_scale

    def __len__(self) -> int:
        return len(self.files)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        path = self.files[idx % len(self.files)]
        img = Image.open(path).convert("RGB")
        w, h = img.size
        low_w, low_h = aspect_size(w, h, self.long_edge)
        high_w, high_h = low_w * self.teacher_scale, low_h * self.teacher_scale
        low = img.resize((low_w, low_h), Image.Resampling.BICUBIC)
        high = img.resize((high_w, high_h), Image.Resampling.BICUBIC)
        return TF.to_tensor(low) * 2.0 - 1.0, TF.to_tensor(high) * 2.0 - 1.0


def tv_loss(x: torch.Tensor) -> torch.Tensor:
    return (x[:, :, 1:, :] - x[:, :, :-1, :]).abs().mean() + (x[:, :, :, 1:] - x[:, :, :, :-1]).abs().mean()


def pixel_grid(x: torch.Tensor) -> torch.Tensor:
    """Approximate deployed 4px lattice: nearest downsample then nearest upsample."""
    h, w = x.shape[-2:]
    grid = torch.nn.functional.interpolate(x, size=(max(1, h // 4), max(1, w // 4)), mode="nearest")
    return torch.nn.functional.interpolate(grid, size=(h, w), mode="nearest")


def palette_moments(x: torch.Tensor) -> torch.Tensor:
    """Simple global color statistics in normalized [-1, 1] RGB."""
    flat = x.flatten(2)
    mean = flat.mean(dim=2)
    std = flat.std(dim=2, unbiased=False)
    return torch.cat([mean, std], dim=1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--style-images", type=Path, default=None, help="Optional unpaired pixel-art images for weak style regularization")
    parser.add_argument("--generator", type=Path, default=Path("checkpoints/160_net_G_A.pth"))
    parser.add_argument("--alias", type=Path, default=Path("alias_net.pth"))
    parser.add_argument("--output", type=Path, default=Path("checkpoints/student_lowres.pth"))
    parser.add_argument("--long-edge", type=int, default=128, help="Final bitmap long edge; must be <=128 and divisible by 4")
    parser.add_argument("--teacher-scale", type=int, default=4, help="Run teacher at long_edge*scale, then nearest-downsample to bitmap target")
    parser.add_argument("--resolution", type=int, default=None, help="Deprecated alias for --long-edge")
    parser.add_argument("--width", type=int, default=32)
    parser.add_argument("--blocks", type=int, default=4)
    # Teacher export graph is batch-1 faithful because upstream modulation uses groups=batch.
    # Keep default batch size 1 unless the teacher is reworked for true dynamic batching.
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--steps", type=int, default=20000)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--style-weight", type=float, default=0.0, help="Weight for unpaired multi-cell style prior; try 0.02-0.05")
    parser.add_argument("--style-lattice-weight", type=float, default=0.0, help="Deprecated; keep 0 for true bitmap outputs (nonzero encourages 4x4 block pixels)")
    parser.add_argument("--device", default="mps" if torch.backends.mps.is_available() else "cpu")
    parser.add_argument("--save-every", type=int, default=1000)
    args = parser.parse_args()

    long_edge = args.resolution if args.resolution is not None else args.long_edge
    if long_edge % 4 != 0 or long_edge > 128:
        raise SystemExit("--long-edge must be divisible by 4 and <=128")
    if args.teacher_scale < 1:
        raise SystemExit("--teacher-scale must be >=1")
    if args.batch_size != 1:
        raise SystemExit("aspect-preserving training currently requires --batch-size 1")

    device = torch.device(args.device)
    dataset = BitmapDistillDataset(args.images, long_edge, args.teacher_scale)
    loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=True, num_workers=0, drop_last=True)
    it = iter(loader)

    style_it = None
    if args.style_images is not None and args.style_weight > 0:
        # Pixel art should keep hard edges when resized; nearest is intentional.
        style_dataset = ImageFolderDataset(args.style_images, long_edge, resample=Image.Resampling.NEAREST)
        style_loader = DataLoader(style_dataset, batch_size=1, shuffle=True, num_workers=0, drop_last=True)
        style_it = iter(style_loader)
        print(f"style images: {len(style_dataset)} from {args.style_images}")

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
            x, teacher_x = next(it)
        except StopIteration:
            it = iter(loader)
            x, teacher_x = next(it)
        x = x.to(device)
        teacher_x = teacher_x.to(device)

        with torch.no_grad():
            y_high = teacher(teacher_x).detach()
            y = torch.nn.functional.interpolate(y_high, size=x.shape[-2:], mode="nearest")
        pred = student(x)
        distill_loss = l1(pred, y)
        residual_tv = tv_loss(pred - y)
        lattice_loss = l1(pred, pixel_grid(pred))
        style_loss = pred.new_tensor(0.0)
        if style_it is not None:
            try:
                style = next(style_it)
            except StopIteration:
                style_it = iter(style_loader)
                style = next(style_it)
            style = style.to(device)
            # Unpaired style prior: match coarse RGB palette statistics to real pixel art.
            # This is deliberately weak so it cannot overwrite teacher content.
            style_loss = l1(palette_moments(pred), palette_moments(style))

        loss = (
            distill_loss
            + 0.02 * residual_tv
            + args.style_lattice_weight * lattice_loss
            + args.style_weight * style_loss
        )

        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()

        if step == 1 or step % 50 == 0:
            print(
                f"step={step} loss={loss.item():.6f} "
                f"distill={distill_loss.item():.6f} tv={residual_tv.item():.6f} "
                f"lattice={lattice_loss.item():.6f} style={style_loss.item():.6f}"
            )
        if step % args.save_every == 0 or step == args.steps:
            torch.save({
                "model": student.state_dict(),
                "width": args.width,
                "blocks": args.blocks,
                "long_edge": long_edge,
                "teacher_scale": args.teacher_scale,
                "step": step,
                "params": params,
                "style_images": str(args.style_images) if args.style_images is not None else None,
                "style_weight": args.style_weight,
                "style_lattice_weight": args.style_lattice_weight,
            }, args.output)
            print(f"saved {args.output}")


if __name__ == "__main__":
    main()
