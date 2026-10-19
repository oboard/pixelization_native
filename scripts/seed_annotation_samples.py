#!/usr/bin/env python3
"""Generate every local annotation prediction on Apple MPS, with resumable writes."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "export"))
from model import TestProInference  # noqa: E402

SIZES = (24, 52, 78, 104)
MODEL_VERSION = "python-test-pro-mps"
DATA_ROOT = ROOT / "webui/data"
SOURCE_ROOT = ROOT / "data/pixel_art/non_pixel"


def atomic_text(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)


def inference(model: TestProInference, source: Image.Image, size: int) -> Image.Image:
    model_size = size * 4
    image = source.resize((model_size, model_size), Image.Resampling.BICUBIC)
    array = np.asarray(image, dtype=np.float32) / 127.5 - 1.0
    tensor = torch.from_numpy(array.transpose(2, 0, 1)[None]).to("mps")
    with torch.inference_mode():
        output = model(tensor).detach().to("cpu").numpy()[0]
    rgb = np.clip((output.transpose(1, 2, 0) + 1.0) * 127.5, 0, 255).astype(np.uint8)
    return Image.fromarray(rgb).resize((size, size), Image.Resampling.NEAREST)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", nargs="+", help="Only process these source stems")
    parser.add_argument("--sizes", nargs="+", type=int, default=SIZES)
    parser.add_argument("--limit", type=int, help="Only process the first N source images")
    parser.add_argument("--output-root", type=Path, default=DATA_ROOT)
    args = parser.parse_args()
    if not torch.backends.mps.is_available():
        raise SystemExit("Apple MPS GPU unavailable; CPU fallback is disabled")
    if any(size < 8 or size > 128 for size in args.sizes):
        raise SystemExit("Logical sizes must be between 8 and 128")

    paths = {name: args.output_root / name for name in ("sources", "predictions", "indices")}
    for folder in paths.values():
        folder.mkdir(parents=True, exist_ok=True)
    source_files = sorted(SOURCE_ROOT.glob("*.png"), key=lambda p: (not p.stem.isdigit(), int(p.stem) if p.stem.isdigit() else p.stem))
    if args.ids:
        selected = set(args.ids)
        source_files = [file for file in source_files if file.stem in selected]
        if len(source_files) != len(selected):
            raise SystemExit(f"Missing source IDs: {sorted(selected - {file.stem for file in source_files})}")
    if args.limit:
        source_files = source_files[: args.limit]

    mapping = json.loads((ROOT / "webui/src/app/colorSystemMapping.json").read_text())
    palette = np.array([[int(hex_code[i:i + 2], 16) for i in (1, 3, 5)] for hex_code in mapping], dtype=np.uint8)
    tree = cKDTree(palette.astype(np.float32))
    target_count = len(source_files) * len(args.sizes)
    already = sum(
        (paths["indices"] / f"{file.stem}_{size}.json").exists()
        for file in source_files for size in args.sizes
    )
    print(f"MPS GPU: {len(source_files)} sources × {len(args.sizes)} sizes = {target_count} samples; {already} already complete", flush=True)
    if already == target_count:
        return
    model = TestProInference(ROOT / "checkpoints/160_net_G_A.pth", ROOT / "alias_net.pth").eval().to("mps")
    started = time.monotonic()
    done = already
    errors: list[str] = []
    for source_file in source_files:
        needed = [size for size in args.sizes if not (paths["indices"] / f"{source_file.stem}_{size}.json").exists()]
        if not needed:
            continue
        try:
            with Image.open(source_file) as image:
                source = image.convert("RGB")
            for size in needed:
                sample_id = f"{source_file.stem}_{size}"
                prediction = inference(model, source, size)
                image_array = np.asarray(prediction, dtype=np.uint8)
                indices = tree.query(image_array.reshape(-1, 3), workers=1)[1].astype(np.int16).tolist()
                source_target = paths["sources"] / f"{sample_id}.png"
                prediction_target = paths["predictions"] / f"{sample_id}.png"
                if not source_target.exists():
                    os.link(source_file, source_target)
                prediction.save(prediction_target, format="PNG")
                atomic_text(paths["indices"] / f"{sample_id}.json", {
                    "id": sample_id, "width": size, "height": size,
                    "model_version": MODEL_VERSION, "indices": indices,
                    "status": "pending", "changed_pixels": 0,
                })
                done += 1
                if done % 25 == 0 or done == target_count:
                    elapsed = time.monotonic() - started
                    print(f"{done}/{target_count} ({done / target_count:.1%}), elapsed {elapsed:.1f}s, last {sample_id}", flush=True)
            if done % 300 < len(needed):
                torch.mps.empty_cache()
        except Exception as exc:
            errors.append(f"{source_file.name}: {exc}")
            print(f"ERROR {source_file.name}: {exc}", flush=True)
    if errors:
        raise SystemExit(f"{len(errors)} sources failed; rerun to resume. First errors: {errors[:5]}")
    print(f"COMPLETE {done}/{target_count} in {time.monotonic() - started:.1f}s", flush=True)


if __name__ == "__main__":
    main()
