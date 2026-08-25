#!/usr/bin/env python3
"""Prepare WuZongWei6/Pixelization pixel_art.zip into train/val splits.

Input zip structure observed:
  - Non-pixel art/*.png
  - Multi-cell pixel art/*.png

Output structure:
  data/pixel_art_split/
    train/non_pixel/*.png
    val/non_pixel/*.png
    train/multi_cell/<cell_size>/*.png
    val/multi_cell/<cell_size>/*.png
    manifest.json

The split is deterministic by filename and seed. Multi-cell images are stratified
by their leading cell-size prefix (2_..., 3_..., ..., 8_...).
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def list_images(zip_file: ZipFile) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {"non_pixel": [], "multi_cell": []}
    for name in zip_file.namelist():
        if name.endswith("/"):
            continue
        p = PurePosixPath(name)
        if p.suffix.lower() not in EXTS or len(p.parts) < 2:
            continue
        top = p.parts[0]
        if top == "Non-pixel art":
            buckets["non_pixel"].append(name)
        elif top == "Multi-cell pixel art":
            buckets["multi_cell"].append(name)
    for key in buckets:
        buckets[key].sort()
    return buckets


def split_list(items: list[str], val_ratio: float, seed: int) -> tuple[list[str], list[str]]:
    rng = random.Random(seed)
    items = list(items)
    rng.shuffle(items)
    n_val = max(1, round(len(items) * val_ratio)) if items else 0
    val = sorted(items[:n_val])
    train = sorted(items[n_val:])
    return train, val


def extract(zip_file: ZipFile, members: list[str], dest: Path, flatten_prefix: str | None = None) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for member in members:
        src_name = PurePosixPath(member).name
        if flatten_prefix is None:
            out = dest / src_name
        else:
            out = dest / flatten_prefix / src_name
            out.parent.mkdir(parents=True, exist_ok=True)
        with zip_file.open(member) as src, out.open("wb") as dst:
            shutil.copyfileobj(src, dst)


def cell_prefix(member: str) -> str:
    name = PurePosixPath(member).name
    return name.split("_", 1)[0] if "_" in name else "unknown"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, default=Path("/Users/oboard/Downloads/pixel_art.zip"))
    parser.add_argument("--output", type=Path, default=Path("data/pixel_art_split"))
    parser.add_argument("--val-ratio", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--force", action="store_true", help="Delete output directory before writing")
    args = parser.parse_args()

    if not args.zip.exists():
        raise SystemExit(f"zip not found: {args.zip}")
    if not (0.0 < args.val_ratio < 1.0):
        raise SystemExit("--val-ratio must be between 0 and 1")
    if args.output.exists():
        if not args.force:
            raise SystemExit(f"output already exists: {args.output}; pass --force to replace")
        shutil.rmtree(args.output)

    with ZipFile(args.zip) as z:
        buckets = list_images(z)
        non_train, non_val = split_list(buckets["non_pixel"], args.val_ratio, args.seed)

        multi_by_cell: dict[str, list[str]] = defaultdict(list)
        for member in buckets["multi_cell"]:
            multi_by_cell[cell_prefix(member)].append(member)

        manifest = {
            "source_zip": str(args.zip),
            "output": str(args.output),
            "val_ratio": args.val_ratio,
            "seed": args.seed,
            "splits": {
                "train": {"non_pixel": len(non_train), "multi_cell": {}},
                "val": {"non_pixel": len(non_val), "multi_cell": {}},
            },
        }

        extract(z, non_train, args.output / "train" / "non_pixel")
        extract(z, non_val, args.output / "val" / "non_pixel")

        for cell in sorted(multi_by_cell, key=lambda x: int(x) if x.isdigit() else 999):
            train, val = split_list(multi_by_cell[cell], args.val_ratio, args.seed + int(cell) if cell.isdigit() else args.seed)
            extract(z, train, args.output / "train" / "multi_cell" / cell)
            extract(z, val, args.output / "val" / "multi_cell" / cell)
            manifest["splits"]["train"]["multi_cell"][cell] = len(train)
            manifest["splits"]["val"]["multi_cell"][cell] = len(val)

    manifest_path = args.output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(json.dumps(manifest, indent=2))
    print(f"wrote {manifest_path}")


if __name__ == "__main__":
    main()
