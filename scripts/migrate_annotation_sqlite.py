#!/usr/bin/env python3
"""Import the legacy annotation files into a verified SQLite database."""

import json
import os
import re
import sqlite3
import sys
import zlib
from pathlib import Path

DATA_ROOT = Path(__file__).resolve().parents[1] / "webui/data"
TARGET = DATA_ROOT / "annotation.sqlite3"
TEMP = DATA_ROOT / "annotation.sqlite3.importing"


def status_of(record):
    status = record.get("status")
    if status in {"unmodified", "pending", "human_edited", "qualified", "unqualified"}:
        return status
    if status == "accepted":
        return "qualified"
    if status == "edited":
        return "human_edited" if record.get("annotation_source") == "human" else "pending"
    return "pending" if record.get("corrected_indices") else "unmodified"


def main():
    if TARGET.exists():
        raise SystemExit(f"Database already exists: {TARGET}")
    if TEMP.exists():
        raise SystemExit(f"Incomplete import exists: {TEMP}")
    files = sorted((DATA_ROOT / "indices").glob("*.json"))
    print(f"Importing {len(files)} samples into {TEMP}", flush=True)
    connection = sqlite3.connect(TEMP)
    try:
        connection.executescript("""
            PRAGMA journal_mode=DELETE;
            PRAGMA synchronous=OFF;
            CREATE TABLE samples (
                id TEXT PRIMARY KEY, sort_key TEXT NOT NULL, width INTEGER NOT NULL,
                height INTEGER NOT NULL, model_version TEXT NOT NULL, status TEXT NOT NULL,
                changed_pixels INTEGER NOT NULL DEFAULT 0, reviewed_at TEXT,
                review_reason TEXT, review_history TEXT, history_count INTEGER NOT NULL DEFAULT 0,
                has_corrected INTEGER NOT NULL DEFAULT 0, has_meta INTEGER NOT NULL DEFAULT 0,
                record BLOB NOT NULL
            );
            CREATE TABLE images (id TEXT NOT NULL, kind TEXT NOT NULL, png BLOB NOT NULL,
                PRIMARY KEY (id, kind));
            CREATE TABLE metadata (id TEXT PRIMARY KEY, json TEXT NOT NULL);
            CREATE TABLE assets (path TEXT PRIMARY KEY, content BLOB NOT NULL);
        """)
        for index, file in enumerate(files, 1):
            raw = file.read_bytes()
            record = json.loads(raw)
            sample_id = file.stem
            if record.get("id") != sample_id:
                raise ValueError(f"ID mismatch: {file}")
            status = status_of(record)
            history = record.get("review_history")
            if not isinstance(history, list) or not history:
                history = ([{"from": None, "to": status,
                             "reason": record.get("review_reason", ""),
                             "timestamp": record.get("reviewed_at")}] if status in {"qualified", "unqualified"} else [])
            key = re.sub(r"\d+", lambda match: match.group().zfill(12), sample_id)
            meta_file = DATA_ROOT / "meta" / f"{sample_id}.json"
            connection.execute("""INSERT INTO samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                sample_id, key, record["width"], record["height"], record.get("model_version", "unknown"),
                status, record.get("changed_pixels", 0), record.get("reviewed_at"),
                record.get("review_reason"), json.dumps(history, separators=(",", ":")), len(history),
                int(bool(record.get("corrected_indices"))), int(meta_file.exists()),
                zlib.compress(raw, level=1),
            ))
            if meta_file.exists():
                connection.execute("INSERT INTO metadata VALUES (?, ?)", (sample_id, meta_file.read_text()))
            for kind in ("predictions", "corrected", "edit_masks"):
                image = DATA_ROOT / kind / f"{sample_id}.png"
                if image.exists():
                    connection.execute("INSERT INTO images VALUES (?, ?, ?)", (sample_id, kind, image.read_bytes()))
            if index % 500 == 0:
                connection.commit()
                print(f"{index}/{len(files)}", flush=True)
        connection.commit()
        for file in (DATA_ROOT / "reviews").rglob("*"):
            if file.is_file():
                connection.execute("INSERT INTO assets VALUES (?, ?)",
                                   (str(file.relative_to(DATA_ROOT)), file.read_bytes()))
        connection.commit()
        connection.executescript("""
            CREATE INDEX samples_sort ON samples(sort_key);
            CREATE INDEX samples_review ON samples(status, has_corrected, sort_key);
            CREATE INDEX samples_history ON samples(history_count, reviewed_at);
            CREATE INDEX samples_size ON samples(width, sort_key);
        """)
        sample_count = connection.execute("SELECT count(*) FROM samples").fetchone()[0]
        image_count = connection.execute("SELECT count(*) FROM images").fetchone()[0]
        meta_count = connection.execute("SELECT count(*) FROM metadata").fetchone()[0]
        asset_count = connection.execute("SELECT count(*) FROM assets").fetchone()[0]
        expected_images = sum(len(list((DATA_ROOT / kind).glob("*.png"))) for kind in ("predictions", "corrected", "edit_masks"))
        expected_meta = len(list((DATA_ROOT / "meta").glob("*.json")))
        expected_assets = sum(file.is_file() for file in (DATA_ROOT / "reviews").rglob("*"))
        if sample_count != len(files) or image_count != expected_images or meta_count != expected_meta or asset_count != expected_assets:
            raise ValueError(f"Count mismatch: samples {sample_count}/{len(files)}, images {image_count}/{expected_images}, metadata {meta_count}/{expected_meta}, assets {asset_count}/{expected_assets}")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed")
        connection.close()
        os.replace(TEMP, TARGET)
        print(f"Verified: {sample_count} samples, {image_count} images, {meta_count} metadata, {asset_count} assets; database: {TARGET}", flush=True)
    except Exception:
        connection.close()
        raise


if __name__ == "__main__":
    main()
