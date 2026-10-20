#!/usr/bin/env python3
"""Build reviewable palette-index annotations for simple flat-color images.

Each recipe is tied to an image number. Add a recipe only after inspecting its
source. `preview` never changes annotations; `apply` requires an existing
preview and refuses to replace an annotation unless --force is supplied.

Use through the main annotation CLI:
    node scripts/pixel_annotate.mjs recipe-list
    node scripts/pixel_annotate.mjs recipe-preview 122
    node scripts/pixel_annotate.mjs recipe-apply 122
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "webui" / "data"
REVIEWS = DATA / "reviews" / "recipes"
PALETTE = list(json.loads((ROOT / "webui/src/app/colorSystemMapping.json").read_text()))
SIZES = (24, 52, 78, 104)
RECIPE_NAMES = {
    31: "five-petal flower",
    45: "Mickey and Minnie silhouettes",
    47: "two conifers",
    50: "apple",
    102: "sad emoji",
    105: "five-point star",
    109: "green book with red spine",
    117: "rounded tree",
    122: "red fedora",
    146: "basketball",
    152: "solid red heart",
    160: "yellow butterfly",
    165: "green tree with brown trunk",
    170: "mouse and cheese",
    179: "yellow bird with raised wing",
    182: "two flowers",
    228: "faceted red star",
    241: "Mickey silhouette with buttons",
    258: "five-petal green flower",
    284: "red apple with leaf",
    286: "yellow outlined star",
    323: "palm tree",
    357: "sad yellow face",
    375: "green leaf with veins",
}


def cover(mask: np.ndarray, size: int) -> np.ndarray:
    """Fraction of source-class pixels within each logical pixel."""
    height, width = mask.shape
    ys = np.linspace(0, height, size + 1, dtype=int)
    xs = np.linspace(0, width, size + 1, dtype=int)
    result = np.zeros((size, size), dtype=np.float32)
    for y in range(size):
        for x in range(size):
            result[y, x] = mask[ys[y] : ys[y + 1], xs[x] : xs[x + 1]].mean()
    return result


def classes(source: np.ndarray, size: int, recipe_id: int) -> np.ndarray:
    """Return MARD indices, with -1 for transparent cells."""
    r, g, b = source.astype(np.float32).transpose(2, 0, 1)
    result = np.full((size, size), -1, dtype=np.int16)
    threshold = 0.4 if size == 24 else 0.42 if size == 52 else 0.5

    if recipe_id == 31:  # Flat purple five-petal flower.
        purple = cover((b > 180) & (r < 230) & (g < 180), size)
        result[purple >= threshold] = 91

    elif recipe_id == 45:  # Mickey and Minnie silhouettes and bow.
        black = cover((r < 90) & (g < 90) & (b < 90), size)
        pink = cover((r > 130) & (g < 130) & (b < 200) & (r > g * 1.6), size)
        result[black >= threshold] = 189
        result[pink >= 0.2 if size == 24 else pink >= 0.25] = 250
        if size == 24:
            result[9:12, 15:20] = 189
            for x, y in ((16, 9), (19, 9), (15, 10), (16, 10),
                         (17, 10), (18, 10), (19, 10), (16, 11), (18, 11)):
                result[y, x] = 250
            result[10, 17] = 144

    elif recipe_id == 47:  # Two overlapping conifers.
        dark = cover((r < 65) & (g < 125) & (b < 100), size)
        light = cover((r >= 65) & (r < 170) & (g > 110) & (g < 200) & (b < 175), size)
        present = np.maximum(dark, light) >= 0.4
        result[present & (dark > light)] = 37
        result[present & (light >= dark)] = 235

    elif recipe_id == 50:  # Apple, leaf and stem.
        apple = cover((r > 200) & (g > 130) & (g < 235) & (b < 120), size)
        leaf = cover((g > r * 1.1) & (g > b * 1.3) & (b < 180), size)
        stem = cover((r > 75) & (r < 220) & (g > 35) & (g < 160)
                     & (b < 125) & (r > g * 1.15), size)
        result[stem >= (0.08 if size == 24 else 0.12)] = 168
        result[leaf >= (0.18 if size == 24 else 0.30)] = 42
        result[apple >= (0.23 if size == 24 else 0.35)] = 25
        # Keep the characteristic leaf vein without introducing isolated specks.
        if size == 24:
            vein = ((6, 2), (7, 3), (8, 4), (9, 5),
                    (10, 6), (7, 4), (10, 5))
        elif size == 52:
            vein = ((13, 5), (16, 8), (19, 11), (22, 14), (25, 17))
            if result[20, 27] == 168:
                result[20, 27] = 25
        else:
            vein = ()
        for x, y in vein:
            if result[y, x] == 42:
                result[y, x] = 54

    elif recipe_id == 102:  # Sad emoji: eyes, frown, rim and shadow.
        black = cover((r < 70) & (g < 70) & (b < 70), size)
        gray = cover((r > 55) & (r < 155) & (abs(r - g) < 18)
                     & (abs(g - b) < 18), size)
        olive = cover((r > 70) & (r < 200) & (g > 60) & (g < 180)
                      & (b < 100), size)
        face = cover((r > 180) & (g > 110) & ((r - b) > 30), size)
        for y in range(size):
            result[y, face[y] >= 0.35] = 3 if y < size * 0.375 else 4 if y < size * 0.625 else 25
        result[olive >= 0.23] = 51
        result[gray >= 0.22] = 261
        result[black >= 0.3] = 189

    elif recipe_id == 105:  # Solid five-point star.
        yellow = cover((r > 220) & (g > 125) & (b < 100), size)
        result[yellow >= threshold] = 25

    elif recipe_id == 109:  # Green book: keep white pages separate from background.
        height, width = r.shape
        art = Image.new('I', (size, size), -1)
        draw = ImageDraw.Draw(art)
        def point(x, y):
            return (round(x * (size - 1) / (width - 1)),
                    round(y * (size - 1) / (height - 1)))
        def polygon(points, color):
            draw.polygon([point(*p) for p in points], fill=color)
        # Build solid surfaces first; draw their boundaries once afterward.
        polygon([(4, 378), (203, 1), (501, 13), (319, 403)], 37)
        polygon([(4, 378), (203, 1), (255, 2), (65, 382)], 249)
        polygon([(4, 378), (319, 403), (319, 494), (4, 477)], 184)
        polygon([(319, 403), (501, 13), (501, 98), (319, 494)], 184)
        for start, end in [
            ((4, 378), (203, 1)), ((203, 1), (501, 13)),
            ((501, 13), (319, 403)), ((319, 403), (4, 378)),
            ((255, 2), (65, 382)),
            ((4, 378), (4, 477)), ((4, 477), (319, 494)),
            ((319, 494), (501, 98)), ((501, 98), (501, 13)),
            ((319, 403), (319, 494)),
        ]:
            draw.line([point(*start), point(*end)], fill=1, width=1)
        draw.line([point(4, 483), point(319, 500), point(506, 99)],
                  fill=37, width=1)
        result = np.asarray(art, dtype=np.int16).copy()
        result[result == 1] = 189

    elif recipe_id == 117:  # Rounded tree canopy and trunk.
        green = cover((r < 100) & (g > 70) & (g < 200) & (b < 100), size)
        brown = cover((r > 70) & (r < 190) & (g < 120) & (b < 90)
                      & (r > g * 1.2), size)
        result[brown >= threshold] = 146
        result[green >= threshold] = 37

    elif recipe_id == 122:  # Red fedora, dark band and pink highlights.
        red = cover((r > 150) & (g < 110) & (b < 115), size)
        black = cover((r < 70) & (g < 70) & (b < 70), size)
        gray = cover((r >= 70) & (r < 145) & (abs(r - g) < 18)
                     & (abs(g - b) < 18), size)
        highlight = cover((r > 190) & (g >= 70) & (g < 150)
                          & (b >= 70) & (b < 160), size)
        result[red >= 0.35] = 141
        result[highlight >= 0.35] = 148
        result[gray >= 0.3] = 261
        result[black >= (0.22 if size == 24 else 0.35)] = 189

    elif recipe_id == 146:  # Basketball: three warm leather tones and seams.
        leather = (r > 75) & (r < 245) & (g > 35) & (g < 190)
        dark = cover(leather & (r < 155), size)
        mid = cover(leather & (r >= 155) & (r < 195), size)
        light = cover(leather & (r >= 195), size)
        black = cover((r < 65) & (g < 65) & (b < 65), size)
        result[dark >= threshold] = 146
        result[mid >= threshold] = 174
        result[light >= threshold] = 153
        result[black >= (0.18 if size == 24 else 0.3)] = 189

    elif recipe_id == 152:  # Solid red heart, with antialiased white edge removed.
        red = cover((r > 145) & (g < 125) & (b < 125), size)
        result[red >= (0.32 if size == 24 else 0.45)] = 141

    elif recipe_id == 160:  # Butterfly: single yellow field and black marks.
        yellow = cover((r > 190) & (g > 155) & (b < 105), size)
        black = cover((r < 95) & (g < 95) & (b < 95), size)
        result[yellow >= threshold] = 252
        result[black >= (0.18 if size == 24 else 0.28)] = 189

    elif recipe_id == 165:  # Two clean source-color regions, no shading.
        green = cover((g > 90) & (r < 170) & (b < 105), size)
        brown = cover((r > 95) & (r < 210) & (g < 135)
                      & (b < 85) & (r > g * 1.3), size)
        result[green >= threshold] = 42
        result[brown >= (0.3 if size == 24 else threshold)] = 181

    elif recipe_id == 170:  # Brown mouse, coral ear/tail and yellow cheese.
        brown = cover((r > 70) & (r < 185) & (g > 30) & (g < 110)
                      & (b < 85) & (r > g * 1.4), size)
        coral = cover((r > 175) & (g > 70) & (g < 155)
                      & (b > 35) & (b < 120), size)
        cheese = cover((r > 195) & (g > 115) & (b < 100), size)
        result[brown >= (0.3 if size == 24 else threshold)] = 146
        result[coral >= (0.22 if size == 24 else 0.35)] = 13
        result[cheese >= threshold] = 25

    elif recipe_id == 179:  # Yellow bird: body, wing, beak and eye.
        body = cover((r > 215) & (g > 145) & (g < 230) & (b < 95), size)
        wing = cover((r > 225) & (g > 225) & (b < 110), size)
        beak = cover((r > 220) & (g > 175) & (b > 105) & (b < 210), size)
        eye = cover((r < 105) & (g < 105) & (b < 110), size)
        eye_shine = cover((r > 195) & (g > 195) & (b > 195)
                          & ((np.indices(r.shape)[1] - 113) ** 2 / 24 ** 2
                             + (np.indices(r.shape)[0] - 113) ** 2 / 42 ** 2 < 1), size)
        result[body >= threshold] = 25
        result[wing >= threshold] = 246
        result[beak >= (0.3 if size == 24 else threshold)] = 20
        result[eye >= (0.2 if size == 24 else 0.35)] = 189
        result[eye_shine >= (0.22 if size == 24 else 0.35)] = 184

    elif recipe_id == 182:  # Purple and pink flowers with two centers and stems.
        purple = cover((r > 105) & (r < 220) & (g > 95) & (g < 190)
                       & (b > 145) & (b > r), size)
        pink = cover((r > 185) & (g < 105) & (b > 45) & (b < 175), size)
        cream = cover((r > 220) & (g > 175) & (b > 105) & (b < 215), size)
        light_pink = cover((r > 220) & (g > 115) & (g < 220)
                           & (b > 140) & (b < 235), size)
        green = cover((g > 35) & (g < 135) & (r < 100) & (b < 95)
                      & (g > r * 1.3), size)
        dark = cover((r < 75) & (g < 75) & (b < 75), size)
        result[purple >= threshold] = 276
        result[pink >= threshold] = 250
        result[cream >= threshold] = 20
        result[light_pink >= threshold] = 131
        result[dark >= (0.2 if size == 24 else 0.3)] = 198
        result[green >= (0.25 if size == 24 else 0.4)] = 37

    elif recipe_id == 228:  # Red star with darker folded facets.
        red = cover((r > 135) & (g < 75) & (b < 90), size)
        shade = cover((r > 95) & (r < 205) & (g < 55) & (b < 80), size)
        result[red >= threshold] = 141
        result[shade >= (0.55 if size == 24 else 0.6)] = 143

    elif recipe_id == 241:  # Black ears, red shorts and two yellow buttons.
        black = cover((r < 75) & (g < 75) & (b < 75), size)
        red = cover((r > 110) & (g < 90) & (b < 90), size)
        yellow = cover((r > 185) & (g > 135) & (b < 115), size)
        result[black >= threshold] = 189
        result[red >= threshold] = 249
        result[yellow >= (0.3 if size == 24 else threshold)] = 25

    elif recipe_id == 258:  # Solid green flower with a transparent central hole.
        green = cover((r < 150) & (g > 115) & (b < 115), size)
        result[green >= threshold] = 29

    elif recipe_id == 284:  # Red apple with green leaf, brown stem and black ink.
        red = cover((r > 155) & (g < 95) & (b < 95), size)
        green = cover((g > 95) & (r < 145) & (b < 105), size)
        brown = cover((r > 100) & (r < 215) & (g > 45) & (g < 165)
                      & (b < 95) & (r > g * 1.2), size)
        black = cover((r < 75) & (g < 75) & (b < 75), size)
        result[red >= threshold] = 141
        result[green >= (0.3 if size == 24 else threshold)] = 29
        result[brown >= (0.3 if size == 24 else threshold)] = 181
        result[black >= (0.2 if size == 24 else 0.3)] = 189

    elif recipe_id == 286:  # Two-color outlined star.
        yellow = cover((r > 205) & (g > 205) & (b < 95), size)
        black = cover((r < 85) & (g < 85) & (b < 85), size)
        result[yellow >= threshold] = 246
        result[black >= (0.2 if size == 24 else 0.3)] = 189

    elif recipe_id == 323:  # Palm leaves, curved trunk and small ground patch.
        yy, _ = np.indices(r.shape)
        green = cover((g > 55) & (g > r * 1.3) & (g > b * 1.2)
                      & (r < 135), size)
        brown = (r > 70) & (r < 210) & (g > 35) & (g < 160)
        brown &= (b < 115) & (r > g * 1.12)
        trunk = cover(brown & (yy < 420), size)
        ground = cover(brown & (yy >= 420), size)
        black = cover((r < 65) & (g < 65) & (b < 65), size)
        result[green >= threshold] = 37
        result[trunk >= threshold] = 168
        result[ground >= threshold] = 269
        result[black >= (0.18 if size == 24 else 0.3)] = 189

    elif recipe_id == 375:  # Leaf field, darker rim and vein strokes.
        leaf = cover((g > 120) & (r < 155) & (b < 115)
                     & (g > r * 1.35), size)
        veins = cover((g > 60) & (g < 180) & (r < 95)
                      & (b < 85) & (g > r * 1.5), size)
        result[leaf >= threshold] = 29
        result[veins >= (0.22 if size == 24 else 0.3)] = 37

    elif recipe_id == 357:  # Round yellow face with black frown and eyes.
        yellow = cover((r > 170) & (g > 105) & (b < 115), size)
        black = cover((r < 80) & (g < 80) & (b < 80), size)
        result[yellow >= threshold] = 25
        result[black >= (0.16 if size == 24 else 0.27)] = 189

    else:
        raise ValueError(f"No reviewed recipe for image {recipe_id}")

    return result


def render(indices: np.ndarray) -> Image.Image:
    size = indices.shape[0]
    rgba = np.zeros((size, size, 4), dtype=np.uint8)
    for index in np.unique(indices):
        if index < 0:
            continue
        hex_color = PALETTE[int(index)]
        color = [int(hex_color[i : i + 2], 16) for i in (1, 3, 5)] + [255]
        rgba[indices == index] = color
    return Image.fromarray(rgba, "RGBA")


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def recipe_fingerprint(recipe_id: int, sizes: tuple[int, ...]) -> str:
    digest = hashlib.sha256(Path(__file__).read_bytes())
    digest.update(f"{recipe_id}:{','.join(map(str, sizes))}".encode())
    for size in sizes:
        digest.update((DATA / "sources" / f"{recipe_id}_{size}.png").read_bytes())
    return digest.hexdigest()


def preview(recipe_id: int, sizes: tuple[int, ...]) -> Path:
    REVIEWS.mkdir(parents=True, exist_ok=True)
    canvas = Image.new("RGB", (300 * (len(sizes) + 1), 335), "#eef2f1")
    draw = ImageDraw.Draw(canvas)
    source = Image.open(DATA / "sources" / f"{recipe_id}_{sizes[0]}.png").convert("RGBA")
    source.thumbnail((300, 300), Image.Resampling.LANCZOS)
    canvas.paste(source, ((300 - source.width) // 2, (300 - source.height) // 2), source)
    draw.text((10, 310), f"{recipe_id} source", fill="#24413c")
    for column, size in enumerate(sizes, 1):
        source_rgb = np.asarray(Image.open(DATA / "sources" / f"{recipe_id}_{size}.png").convert("RGB"))
        result = render(classes(source_rgb, size, recipe_id)).resize((300, 300), Image.Resampling.NEAREST)
        cell = Image.new("RGBA", (300, 300), "#eef2f1")
        cell.alpha_composite(result)
        canvas.paste(cell.convert("RGB"), (column * 300, 0))
        draw.text((column * 300 + 10, 310), f"{recipe_id}_{size}", fill="#24413c")
    output = REVIEWS / f"{recipe_id}-{'-'.join(map(str, sizes))}.png"
    canvas.save(output)
    atomic_json(output.with_suffix(".json"), {
        "recipe_id": recipe_id,
        "sizes": list(sizes),
        "fingerprint": recipe_fingerprint(recipe_id, sizes),
    })
    return output


def apply(recipe_id: int, sizes: tuple[int, ...], force: bool) -> None:
    preview_file = REVIEWS / f"{recipe_id}-{'-'.join(map(str, sizes))}.png"
    if not preview_file.exists():
        raise ValueError(f"Review preview first: {preview_file}")
    manifest = preview_file.with_suffix(".json")
    if not manifest.exists() or json.loads(manifest.read_text()).get("fingerprint") != recipe_fingerprint(recipe_id, sizes):
        raise ValueError(f"Preview is stale; regenerate and review: {preview_file}")
    for size in sizes:
        sample_id = f"{recipe_id}_{size}"
        record_file = DATA / "indices" / f"{sample_id}.json"
        record = json.loads(record_file.read_text())
        if not force and (record.get("status", "unmodified") != "unmodified" or "corrected_indices" in record):
            print(f"skip {sample_id}: existing annotation or review state")
            continue
        source = np.asarray(Image.open(DATA / "sources" / f"{sample_id}.png").convert("RGB"))
        indices = classes(source, size, recipe_id)
        flat = indices.ravel().tolist()
        if len(flat) != len(record["indices"]):
            raise ValueError(f"Dimension mismatch: {sample_id}")
        changed = np.asarray(flat) != np.asarray(record["indices"])
        render(indices).save(DATA / "corrected" / f"{sample_id}.png")
        mask = np.zeros((size, size, 4), dtype=np.uint8)
        mask[:, :, :3] = changed.reshape(size, size, 1).astype(np.uint8) * 255
        mask[:, :, 3] = 255
        Image.fromarray(mask, "RGBA").save(DATA / "edit_masks" / f"{sample_id}.png")
        metadata = {
            "id": sample_id,
            "source": f"sources/{sample_id}.png",
            "prediction": f"predictions/{sample_id}.png",
            "corrected": f"corrected/{sample_id}.png",
            "edit_mask": f"edit_masks/{sample_id}.png",
            "width": size,
            "height": size,
            "model_version": record["model_version"],
            "palette": "MARD",
            "accepted_without_edit": False,
            "changed_pixels": int(changed.sum()),
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "annotation_source": "ai",
        }
        atomic_json(DATA / "meta" / f"{sample_id}.json", metadata)
        record["corrected_indices"] = flat
        record["changed_pixels"] = metadata["changed_pixels"]
        record["status"] = "pending"
        record["annotation_source"] = "ai"
        record.pop("reviewed_at", None)
        atomic_json(record_file, record)
        print(f"saved {sample_id}: {metadata['changed_pixels']} changed pixels; pending review")


def main() -> None:
    global DATA, REVIEWS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("list", "preview", "apply"))
    parser.add_argument("ids", type=int, nargs="*", help="source image numbers")
    parser.add_argument("--sizes", type=int, nargs="+", default=list(SIZES))
    parser.add_argument("--data-dir", type=Path, default=DATA)
    parser.add_argument("--force", action="store_true", help="replace existing annotations")
    args = parser.parse_args()
    DATA = args.data_dir.resolve()
    REVIEWS = DATA / "reviews" / "recipes"
    if args.command == "list":
        for recipe_id, name in RECIPE_NAMES.items():
            print(f"{recipe_id:>4}  {name}")
        return
    if not args.ids:
        parser.error("provide at least one source image number")
    sizes = tuple(dict.fromkeys(args.sizes))
    if any(size not in SIZES for size in sizes):
        parser.error(f"sizes must be selected from {SIZES}")
    for recipe_id in args.ids:
        if args.command == "preview":
            print(preview(recipe_id, sizes))
        else:
            apply(recipe_id, sizes, args.force)


if __name__ == "__main__":
    main()
