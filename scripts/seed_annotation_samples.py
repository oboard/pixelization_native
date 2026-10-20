#!/usr/bin/env python3
"""Generate every local annotation prediction on Apple MPS, with resumable writes."""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sqlite3
import sys
import time
import zlib
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
    parser.add_argument("--predict-source", type=Path, help="Predict one uploaded PNG without changing the database")
    parser.add_argument("--prediction-dir", type=Path, help="Directory for four generated PNGs")
    parser.add_argument("--ids", nargs="+", help="Only process these source stems")
    parser.add_argument("--sizes", nargs="+", type=int, default=SIZES)
    parser.add_argument("--limit", type=int, help="Only process the first N source images")
    parser.add_argument("--output-root", type=Path, default=DATA_ROOT)
    args = parser.parse_args()
    if not torch.backends.mps.is_available():
        raise SystemExit("Apple MPS GPU unavailable; CPU fallback is disabled")
    if any(size < 8 or size > 128 for size in args.sizes):
        raise SystemExit("Logical sizes must be between 8 and 128")

    if args.predict_source:
        if not args.prediction_dir:
            raise SystemExit("--prediction-dir is required with --predict-source")
        if not args.predict_source.is_file():
            raise SystemExit(f"Source image missing: {args.predict_source}")
        with Image.open(args.predict_source) as image:
            source = image.convert("RGB")
        model = TestProInference(ROOT / "checkpoints/160_net_G_A.pth", ROOT / "alias_net.pth").eval().to("mps")
        args.prediction_dir.mkdir(parents=True, exist_ok=True)
        for size in args.sizes:
            inference(model, source, size).save(args.prediction_dir / f"{size}.png")
        return
    if args.prediction_dir:
        raise SystemExit("--prediction-dir requires --predict-source")

    args.output_root.mkdir(parents=True, exist_ok=True)
    source_folder = args.output_root / "sources"
    source_folder.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(args.output_root / "annotation.sqlite3")
    database.execute("PRAGMA busy_timeout=5000")
    database.executescript("""
        CREATE TABLE IF NOT EXISTS samples (
            id TEXT PRIMARY KEY, sort_key TEXT NOT NULL, width INTEGER NOT NULL,
            height INTEGER NOT NULL, model_version TEXT NOT NULL, status TEXT NOT NULL,
            changed_pixels INTEGER NOT NULL DEFAULT 0, reviewed_at TEXT,
            review_reason TEXT, review_history TEXT, history_count INTEGER NOT NULL DEFAULT 0,
            has_corrected INTEGER NOT NULL DEFAULT 0, has_meta INTEGER NOT NULL DEFAULT 0,
            record BLOB NOT NULL
        );
        CREATE TABLE IF NOT EXISTS images (
            id TEXT NOT NULL, kind TEXT NOT NULL, png BLOB NOT NULL,
            PRIMARY KEY (id, kind)
        );
        CREATE TABLE IF NOT EXISTS metadata (id TEXT PRIMARY KEY, json TEXT NOT NULL);
    """)
    existing = {row[0] for row in database.execute("SELECT id FROM samples")}
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
        f"{file.stem}_{size}" in existing
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
        needed = [size for size in args.sizes if f"{source_file.stem}_{size}" not in existing]
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
                source_target = source_folder / f"{sample_id}.png"
                if not source_target.exists():
                    os.link(source_file, source_target)
                image_bytes = io.BytesIO()
                prediction.save(image_bytes, format="PNG")
                record = {
                    "id": sample_id, "width": size, "height": size,
                    "model_version": MODEL_VERSION, "indices": indices,
                    "status": "pending", "changed_pixels": 0,
                }
                sort_key = re.sub(r"\d+", lambda match: match.group().zfill(12), sample_id)
                database.execute("""INSERT INTO samples
                    (id, sort_key, width, height, model_version, status, changed_pixels,
                     review_history, history_count, has_corrected, has_meta, record)
                    VALUES (?, ?, ?, ?, ?, ?, 0, '[]', 0, 0, 0, ?)""",
                    (sample_id, sort_key, size, size, MODEL_VERSION, "pending",
                     zlib.compress(json.dumps(record, separators=(",", ":")).encode(), level=1)))
                database.execute("INSERT INTO images (id, kind, png) VALUES (?, 'predictions', ?)",
                                 (sample_id, image_bytes.getvalue()))
                done += 1
                if done % 25 == 0 or done == target_count:
                    database.commit()
                    elapsed = time.monotonic() - started
                    print(f"{done}/{target_count} ({done / target_count:.1%}), elapsed {elapsed:.1f}s, last {sample_id}", flush=True)
            if done % 300 < len(needed):
                torch.mps.empty_cache()
        except Exception as exc:
            errors.append(f"{source_file.name}: {exc}")
            print(f"ERROR {source_file.name}: {exc}", flush=True)
    if errors:
        database.commit()
        database.close()
        raise SystemExit(f"{len(errors)} sources failed; rerun to resume. First errors: {errors[:5]}")
    database.commit()
    database.close()
    print(f"COMPLETE {done}/{target_count} in {time.monotonic() - started:.1f}s", flush=True)


if __name__ == "__main__":
    main()
