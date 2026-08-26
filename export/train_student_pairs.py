#!/usr/bin/env python3
"""Train PixelizationStudent from precomputed bitmap input/target pairs."""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset
import torchvision.transforms.functional as TF
from tqdm import tqdm

from student_model import PixelizationStudent, count_parameters

EXTS = {".png", ".jpg", ".jpeg", ".webp"}


class PairDataset(Dataset):
    def __init__(self, root: Path) -> None:
        self.input_dir = root / "input"
        self.target_dir = root / "target"
        self.inputs = [p for p in sorted(self.input_dir.glob("*")) if p.suffix.lower() in EXTS]
        if not self.inputs:
            raise SystemExit(f"no input images found in {self.input_dir}")
        self.pairs = []
        for inp in self.inputs:
            target = self.target_dir / inp.name
            if target.exists():
                self.pairs.append((inp, target))
        if not self.pairs:
            raise SystemExit(f"no matching pairs found under {root}")

    def __len__(self) -> int:
        return len(self.pairs)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        inp_path, target_path = self.pairs[idx % len(self.pairs)]
        inp = Image.open(inp_path).convert("RGB")
        target = Image.open(target_path).convert("RGB")
        if inp.size != target.size:
            inp = inp.resize(target.size, Image.Resampling.BICUBIC)
        return TF.to_tensor(inp) * 2.0 - 1.0, TF.to_tensor(target) * 2.0 - 1.0


def tv_loss(x: torch.Tensor) -> torch.Tensor:
    return (x[:, :, 1:, :] - x[:, :, :-1, :]).abs().mean() + (x[:, :, :, 1:] - x[:, :, :, :-1]).abs().mean()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("checkpoints/student_ai2pixelart.pth"))
    parser.add_argument("--width", type=int, default=32)
    parser.add_argument("--blocks", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=1, help="Keep 1 for variable aspect-ratio inputs")
    parser.add_argument("--steps", type=int, default=2000)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--device", default="mps" if torch.backends.mps.is_available() else "cpu")
    parser.add_argument("--save-every", type=int, default=500)
    args = parser.parse_args()

    if args.batch_size != 1:
        raise SystemExit("variable aspect-ratio pairs currently require --batch-size 1")

    dataset = PairDataset(args.pairs)
    loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=True, num_workers=0, drop_last=True)
    it = iter(loader)
    device = torch.device(args.device)

    student = PixelizationStudent(width=args.width, blocks=args.blocks).train().to(device)
    params = count_parameters(student)
    print(f"pairs: {len(dataset)} from {args.pairs}")
    print(f"student params: {params:,} ({params * 4 / 1024 / 1024:.2f} MiB raw FP32)")
    if params * 4 >= 10 * 1024 * 1024:
        raise SystemExit("student parameter payload is >=10MB; reduce width/blocks")

    opt = torch.optim.AdamW(student.parameters(), lr=args.lr, betas=(0.9, 0.99), weight_decay=1e-4)
    l1 = nn.L1Loss()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    pbar = tqdm(range(1, args.steps + 1), desc="train")
    for step in pbar:
        try:
            x, y = next(it)
        except StopIteration:
            it = iter(loader)
            x, y = next(it)
        x, y = x.to(device), y.to(device)
        pred = student(x)
        loss = l1(pred, y) + 0.01 * tv_loss(pred - y)

        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
        pbar.set_postfix(loss=f"{loss.item():.4f}")

        if step % args.save_every == 0 or step == args.steps:
            torch.save({
                "model": student.state_dict(),
                "width": args.width,
                "blocks": args.blocks,
                "step": step,
                "params": params,
                "pairs": str(args.pairs),
            }, args.output)
            print(f"saved {args.output}")


if __name__ == "__main__":
    main()
