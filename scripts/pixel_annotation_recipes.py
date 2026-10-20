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
import io
import json
import re
import sqlite3
import tempfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "webui" / "data"
REVIEWS = Path(tempfile.gettempdir()) / "pixel_annotation_reviews" / "recipes"
PALETTE = list(json.loads((ROOT / "webui/src/app/colorSystemMapping.json").read_text()))
SIZES = (24, 52, 78, 104)
PROFILES = ROOT / 'scripts' / 'annotation_profiles'
RECIPE_NAMES = {
    2: "pink starfish with raised right arm",
    10: "solid yellow star",
    25: "girl with pink shirt and pigtails",
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
    341: "green fish with dorsal fin",
    375: "green leaf with veins",
    410: "yellow star with black outline",
    422: "green leaf with diagonal midrib",
    426: "red owl with round eyes",
    428: "blue shark silhouette",
    436: "yellow flower with orange center and green leaf",
    447: "three conifers above brown ground lines",
    468: "orange mango with green leaf",
    498: "white cat with pink bow and overalls",
    505: "smiling yellow duck face with cream bill",
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
    profile_file = PROFILES / f'{recipe_id}.json'
    if profile_file.exists():
        return flat_classes(source, size, json.loads(profile_file.read_text()))

    if recipe_id == 2:  # Preserve source silhouette and enclosed eye whites.
        prototypes = np.array([
            (255, 255, 255), (249, 157, 131), (185, 214, 75),
            (126, 105, 175), (35, 25, 30), (234, 153, 165),
        ], dtype=np.float32)
        labels = ((source.astype(np.float32)[:, :, None, :] - prototypes) ** 2).sum(axis=3).argmin(axis=2)
        white = Image.fromarray((labels == 0).astype(np.uint8) * 255, 'L').copy()
        width, height = white.size
        for x in range(width):
            for y in (0, height - 1):
                if white.getpixel((x, y)) == 255:
                    ImageDraw.floodfill(white, (x, y), 0)
        for y in range(height):
            for x in (0, width - 1):
                if white.getpixel((x, y)) == 255:
                    ImageDraw.floodfill(white, (x, y), 0)
        yy, _ = np.indices(labels.shape)
        eyes = cover((np.asarray(white) == 255) & (yy < height * 0.36), size)
        fractions = np.stack([cover(labels == index, size) for index in range(6)])
        present = (1 - fractions[0] + eyes) >= 0.43
        colors = np.array([-1, 137, 54, 93, 198, 160], dtype=np.int16)
        dominant = fractions[1:].argmax(axis=0) + 1
        result[present] = colors[dominant[present]]
        result[eyes >= 0.24] = 184
        result[present & (fractions[4] >= (0.24 if size == 24 else 0.16))] = 198
        if size == 24:
            result[4:8, 10:17] = np.where(present[4:8, 10:17], 137, -1)
            art = Image.fromarray(result.astype(np.int32), 'I')
            draw = ImageDraw.Draw(art)
            draw.ellipse((10, 4, 16, 7), fill=184)
            draw.point((12, 5), fill=198)
            draw.point((14, 5), fill=198)
            result = np.asarray(art, dtype=np.int16).copy()

    elif recipe_id == 10:  # Bright source star with no dark outline.
        yellow = cover((r > 200) & (g > 190) & (b < 145), size)
        result[yellow >= 0.38] = 246

    elif recipe_id == 25:  # Separate the white collar/eyes from the background.
        prototypes = np.array([
            (255, 255, 255), (0, 0, 0), (250, 216, 190),
            (236, 121, 145), (160, 95, 105), (209, 126, 133),
        ], dtype=np.float32)
        labels = ((source.astype(np.float32)[:, :, None, :] - prototypes) ** 2).sum(axis=3).argmin(axis=2)
        yy, xx = np.indices(labels.shape)
        mouth_region = ((xx >= source.shape[1] * 0.33) & (xx <= source.shape[1] * 0.51)
                        & (yy >= source.shape[0] * 0.56) & (yy <= source.shape[0] * 0.68))
        misplaced_lip = ((labels == 4) | (labels == 5)) & ~mouth_region
        brightness = source.mean(axis=2)
        labels[misplaced_lip & (yy < source.shape[0] * 0.72)] = 2
        labels[misplaced_lip & (yy >= source.shape[0] * 0.72)] = 3
        labels[misplaced_lip & (brightness < 170)] = 1
        white = Image.fromarray((labels == 0).astype(np.uint8) * 255, 'L').copy()
        width, height = white.size
        for x in range(width):
            for y in (0, height - 1):
                if white.getpixel((x, y)) == 255:
                    ImageDraw.floodfill(white, (x, y), 0)
        for y in range(height):
            for x in (0, width - 1):
                if white.getpixel((x, y)) == 255:
                    ImageDraw.floodfill(white, (x, y), 0)
        enclosed = cover(np.asarray(white) == 255, size)
        fractions = np.stack([cover(labels == index, size) for index in range(6)])
        present = (1 - fractions[0] + enclosed) >= 0.45
        colors = np.array([-1, 189, 126, 116, 243, 156], dtype=np.int16)
        dominant = fractions[1:].argmax(axis=0) + 1
        result[present] = colors[dominant[present]]
        result[enclosed >= 0.22] = 184
        result[present & (fractions[1] >= (0.28 if size == 24 else 0.18))
               & (fractions[1] >= enclosed)] = 189
        if size == 24:
            for y in range(18, 24):
                for x in range(3, 19):
                    if result[y, x] == 189 and fractions[3, y, x] + enclosed[y, x] > 0.3:
                        result[y, x] = 116 if fractions[3, y, x] >= enclosed[y, x] else 184
            art = Image.fromarray(result.astype(np.int32), 'I')
            draw = ImageDraw.Draw(art)
            draw.ellipse((5, 7, 8, 11), fill=184)
            draw.ellipse((6, 8, 7, 10), fill=189)
            draw.point((7, 8), fill=184)
            draw.ellipse((12, 9, 16, 13), fill=184)
            draw.rectangle((14, 10, 15, 12), fill=189)
            draw.point((15, 10), fill=184)
            draw.point((9, 12), fill=189)
            result = np.asarray(art, dtype=np.int16).copy()

    elif recipe_id == 31:  # Flat purple five-petal flower.
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
        if size == 52 and result[20, 27] == 168:
            result[20, 27] = 25
        # Keep the characteristic leaf vein without introducing isolated specks.
        if size == 24:
            vein = ((6, 2), (7, 3), (8, 4), (9, 5),
                    (10, 6), (7, 4), (10, 5))
        else:
            vein = ()
        for x, y in vein:
            if result[y, x] == 42:
                result[y, x] = 54
        if size >= 52:
            # The source's thin white veins break into scattered empty cells
            # when sampled. Close only small gaps within the green leaf.
            leaf_image = Image.fromarray((result == 42).astype(np.uint8) * 255, 'L')
            window = 5
            closed = leaf_image.filter(ImageFilter.MaxFilter(window)).filter(
                ImageFilter.MinFilter(window))
            fill = (np.asarray(closed) > 0) & (result < 0)
            result[fill] = 42
            # The tiny white glint beside the stem is discontinuous after
            # sampling. Simplify it away inside the apple surface.
            for y in range(round(size * 0.34), round(size * 0.43)):
                for x in range(round(size * 0.4), round(size * 0.56)):
                    if result[y, x] < 0 and np.sum(
                        result[y - 1:y + 2, x - 1:x + 2] == 25) >= 4:
                        result[y, x] = 25

    elif recipe_id == 102:  # Sad emoji: eyes, frown, rim and shadow.
        black = cover((r < 70) & (g < 70) & (b < 70), size)
        gray = cover((r > 55) & (r < 155) & (abs(r - g) < 18)
                     & (abs(g - b) < 18), size)
        olive = cover((r > 70) & (r < 200) & (g > 60) & (g < 180)
                      & (b < 100), size)
        face = cover((r > 180) & (g > 110) & ((r - b) > 30), size)
        for y in range(size):
            result[y, face[y] >= 0.35] = 4
        result[olive >= 0.23] = 51
        result[gray >= 0.22] = 261
        black[round(size * 0.45):round(size * 0.73)] = 0
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
        # Close antialiasing pinholes inside the ball without extending its
        # silhouette. Prefer dark ink where a seam runs through the gap.
        for _ in range(2):
            repaired = result.copy()
            for y in range(1, size - 1):
                for x in range(1, size - 1):
                    if result[y, x] >= 0:
                        continue
                    neighbors = [result[y - 1, x], result[y + 1, x],
                                 result[y, x - 1], result[y, x + 1]]
                    colors = [int(value) for value in neighbors if value >= 0]
                    if len(colors) >= 3:
                        repaired[y, x] = max(set(colors), key=lambda value: (colors.count(value), value == 189))
            result = repaired
        foreground = cover((r < 225) | (g < 225) | (b < 225), size)
        repaired = result.copy()
        for y in range(1, size - 1):
            for x in range(1, size - 1):
                if result[y, x] >= 0 or foreground[y, x] < 0.55:
                    continue
                neighbors = result[y - 1:y + 2, x - 1:x + 2].ravel()
                colors = [int(value) for value in neighbors if value >= 0]
                if colors:
                    repaired[y, x] = 189 if black[y, x] >= 0.12 else max(
                        set(colors), key=lambda value: colors.count(value))
        result = repaired

    elif recipe_id == 152:  # Solid red heart, with antialiased white edge removed.
        red = cover((r > 145) & (g < 125) & (b < 125), size)
        result[red >= (0.32 if size == 24 else 0.45)] = 141

    elif recipe_id == 160:  # Butterfly: single yellow field and black marks.
        yellow = cover((r > 190) & (g > 155) & (b < 105), size)
        black = cover((r < 95) & (g < 95) & (b < 95), size)
        result[yellow >= threshold] = 252
        result[black >= (0.18 if size == 24 else 0.28)] = 189
        # These cells are tiny transparent holes fully enclosed by the wings.
        enclosed_holes = {
            78: ((15, 41),),
            104: ((20, 55), (27, 11), (82, 72), (83, 72)),
        }
        for x, y in enclosed_holes.get(size, ()):
            if result[y, x] < 0 and yellow[y, x] > black[y, x]:
                result[y, x] = 252
    elif recipe_id == 165:  # Two clean source-color regions, no shading.
        green = cover((g > 90) & (r < 170) & (b < 105), size)
        brown = cover((r > 95) & (r < 210) & (g < 135)
                      & (b < 85) & (r > g * 1.3), size)
        result[green >= threshold] = 42
        result[brown >= (0.3 if size == 24 else threshold)] = 181
        if size == 24:
            result[13, 10] = 181  # Join the left branch to the trunk.

    elif recipe_id == 170:  # Brown mouse, coral ear/tail and yellow cheese.
        _, xx = np.indices(r.shape)
        brown = cover((r > 70) & (r < 185) & (g > 30) & (g < 110)
                      & (b < 85) & (r > g * 1.4), size)
        coral = cover((r > 175) & (g > 70) & (g < 155)
                      & (b > 35) & (b < 120), size)
        cheese = cover((r > 195) & (g > 115) & (b < 100)
                       & (xx < r.shape[1] * 0.34), size)
        result[brown >= (0.3 if size == 24 else threshold)] = 146
        result[coral >= (0.22 if size == 24 else 0.35)] = 13
        result[cheese >= threshold] = 25
        if size == 52:
            result[28, 16] = result[29, 16] = 146  # Nose-to-snout join.
            for x, y in ((44, 20), (45, 21), (46, 22), (47, 23)):
                result[y, x] = 13
        elif size == 78:
            result[43, 23] = result[44, 24] = 146
            result[30, 66] = 13
            for x, y, color in ((64, 22, 146), (64, 23, 146),
                                (63, 23, 146), (63, 26, 13),
                                (64, 26, 13), (64, 27, 13)):
                result[y, x] = color

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
        if size == 104 and result[25, 10] < 0:
            result[25, 10] = 25  # Close the one-cell gap beside the beak.

    elif recipe_id == 182:  # Mutually exclusive source colors, including white.
        prototypes = np.array([
            (255, 255, 255), (160, 140, 206), (247, 33, 104),
            (254, 227, 154), (253, 181, 208), (0, 64, 0), (30, 30, 30),
        ], dtype=np.float32)
        distances = ((source.astype(np.float32)[:, :, None, :] - prototypes) ** 2).sum(axis=3)
        labels = distances.argmin(axis=2)
        fractions = np.stack([cover(labels == index, size) for index in range(len(prototypes))])
        present = (1 - fractions[0]) >= 0.46
        dominant = fractions[1:].argmax(axis=0) + 1
        colors = np.array([-1, 276, 250, 20, 131, 37, 198], dtype=np.int16)
        result[present] = colors[dominant[present]]
        result[present & (fractions[6] >= 0.16)] = 198

    elif recipe_id == 228:  # Red star with darker folded facets.
        red = cover((r > 135) & (g < 75) & (b < 90), size)
        shade = cover((r > 95) & (r < 205) & (g < 55) & (b < 80), size)
        result[red >= threshold] = 141
        result[shade >= (0.55 if size == 24 else 0.6)] = 143
        # Antialiased facet intersections can fall below both color thresholds.
        # The center of this particular star is solid in the source.
        center = size // 2
        result[center - 2:center + 5, center - 3:center + 3][
            result[center - 2:center + 5, center - 3:center + 3] < 0
        ] = 143

    elif recipe_id == 241:  # Black ears, red shorts and two yellow buttons.
        black = cover((r < 75) & (g < 75) & (b < 75), size)
        red = cover((r > 110) & (g < 90) & (b < 90), size)
        yellow = cover((r > 185) & (g > 135) & (b < 115), size)
        result[black >= threshold] = 189
        result[red >= (0.22 if size == 24 else 0.3)] = 249
        result[yellow >= (0.3 if size == 24 else threshold)] = 25
        if size == 24:
            result[14:20, 8:16][result[14:20, 8:16] == 25] = 249
            for cx in (10, 13):
                result[15:20, cx] = 25
                result[16:19, cx + 1] = 25
        elif size in (52, 78):
            result[result == 25] = 249
            if size == 52:
                buttons = ((22, 37.5, 1.45, 4.7), (29, 37.5, 1.45, 4.7))
            else:
                buttons = ((33, 57, 2.45, 7.2), (44, 57, 2.45, 7.2))
            yy, xx = np.indices(result.shape)
            for cx, cy, rx, ry in buttons:
                oval = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1
                result[oval & (result == 249)] = 25

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
        result[black >= (0.2 if size == 24 else 0.12)] = 189

    elif recipe_id == 286:  # Two-color outlined star.
        yellow = cover((r > 205) & (g > 205) & (b < 95), size)
        black = cover((r < 85) & (g < 85) & (b < 85), size)
        result[yellow >= threshold] = 246
        result[black >= (0.36 if size == 24 else 0.3)] = 189
        if size == 104:
            # Every enclosed transparent cell in this version falls on the
            # black/yellow boundary; close the antialiasing pinholes.
            visited = np.zeros((size, size), dtype=bool)
            for y in range(size):
                for x in range(size):
                    if visited[y, x] or result[y, x] >= 0:
                        continue
                    component = [(x, y)]
                    visited[y, x] = True
                    for cx, cy in component:
                        for nx, ny in ((cx - 1, cy), (cx + 1, cy),
                                       (cx, cy - 1), (cx, cy + 1)):
                            if (0 <= nx < size and 0 <= ny < size
                                    and not visited[ny, nx] and result[ny, nx] < 0):
                                visited[ny, nx] = True
                                component.append((nx, ny))
                    if (len(component) <= 2 and all(0 < cx < size - 1
                                                    and 0 < cy < size - 1
                                                    for cx, cy in component)):
                        for cx, cy in component:
                            result[cy, cx] = 189

    elif recipe_id == 323:  # Palm silhouette with one source class per pixel.
        prototypes = np.array([
            (255, 255, 255), (8, 130, 69), (81, 125, 43),
            (142, 88, 36), (166, 125, 45), (25, 35, 26),
        ], dtype=np.float32)
        distances = ((source.astype(np.float32)[:, :, None, :] - prototypes) ** 2).sum(axis=3)
        labels = distances.argmin(axis=2)
        fractions = np.stack([cover(labels == index, size) for index in range(len(prototypes))])
        present = (1 - fractions[0]) >= 0.46
        dominant = fractions[1:].argmax(axis=0) + 1
        colors = np.array([-1, 37, 37, 168, 269, 189], dtype=np.int16)
        result[present] = colors[dominant[present]]
        result[present & (fractions[5] >= 0.16)] = 189
        yy, _ = np.indices(result.shape)
        result[((result == 168) | (result == 269)) & (yy < size * 420 / source.shape[0])] = 168
        result[((result == 168) | (result == 269)) & (yy >= size * 420 / source.shape[0])] = 269
        if size >= 52:
            padded = np.pad(present, 1)
            interior = (padded[1:-1, 1:-1] & padded[:-2, 1:-1]
                        & padded[2:, 1:-1] & padded[1:-1, :-2]
                        & padded[1:-1, 2:])
            inner_pad = np.pad(interior, 1)
            deep = (inner_pad[1:-1, 1:-1] & inner_pad[:-2, 1:-1]
                    & inner_pad[2:, 1:-1] & inner_pad[1:-1, :-2]
                    & inner_pad[1:-1, 2:])
            band = interior & ~deep & (result == 189) & (fractions[5] < 0.5)
            surface = colors[fractions[1:5].argmax(axis=0) + 1]
            result[band] = surface[band]
            result[present & ~interior & (yy < size * 0.83)] = 189

    elif recipe_id == 341:  # Flat fish, dark fin, white eye and thin ink.
        prototypes = np.array([(255, 255, 255), (137, 202, 28),
                               (101, 150, 20), (25, 30, 20)], dtype=np.float32)
        labels = ((source.astype(np.float32)[:, :, None, :] - prototypes) ** 2).sum(axis=3).argmin(axis=2)
        fractions = np.stack([cover(labels == index, size) for index in range(4)])
        present = (1 - fractions[0]) >= 0.44
        dominant = fractions[1:].argmax(axis=0) + 1
        colors = np.array([-1, 39, 42, 189], dtype=np.int16)
        result[present] = colors[dominant[present]]
        yy, xx = np.indices(r.shape)
        eye_region = ((xx - 104) / 17) ** 2 + ((yy - 202) / 33) ** 2 <= 1
        eye_white = cover((labels == 0) & eye_region, size)
        result[eye_white >= 0.25] = 184
        result[(present | (eye_white > 0)) & (fractions[3] >= 0.14)] = 189
        if size >= 52:
            padded = np.pad(present, 1)
            interior = (padded[1:-1, 1:-1] & padded[:-2, 1:-1]
                        & padded[2:, 1:-1] & padded[1:-1, :-2]
                        & padded[1:-1, 2:])
            result[present & ~interior] = 189

    elif recipe_id == 375:  # Leaf field, darker rim and vein strokes.
        leaf = cover((g > 120) & (r < 155) & (b < 115)
                     & (g > r * 1.35), size)
        veins = cover((g > 60) & (g < 180) & (r < 95)
                      & (b < 85) & (g > r * 1.5), size)
        result[leaf >= threshold] = 29
        result[veins >= (0.22 if size == 24 else 0.3)] = 37

    elif recipe_id == 410:  # Two flat source colors and a continuous border.
        prototypes = np.array([(248, 248, 248), (255, 255, 0), (0, 0, 0)], dtype=np.float32)
        labels = ((source.astype(np.float32)[:, :, None, :] - prototypes) ** 2).sum(axis=3).argmin(axis=2)
        yellow = cover(labels == 1, size)
        ink = cover(labels == 2, size)
        yellow = (yellow + np.fliplr(yellow)) / 2
        ink = (ink + np.fliplr(ink)) / 2
        present = yellow + ink >= 0.44
        result[present] = 246
        result[present & (ink >= (0.32 if size == 24 else 0.24))] = 189
        if size == 24:
            padded = np.pad(present, 1)
            interior = (padded[1:-1, 1:-1] & padded[:-2, 1:-1]
                        & padded[2:, 1:-1] & padded[1:-1, :-2]
                        & padded[1:-1, 2:])
            result[present & ~interior] = 189

    elif recipe_id == 422:  # Flat leaf field and a continuous main vein/stem.
        green = cover((g > r * 1.3) & (g > b * 1.5) & (g > 60), size)
        present = green >= 0.43
        result[present] = 29
        line = Image.new('L', (size, size), 0)
        ImageDraw.Draw(line).line([(0, 0), (size - 1, size - 1)],
                                 fill=255, width=max(1, round(size * 12 / 512)))
        result[present & (np.asarray(line) > 0)] = 36
        yy, xx = np.indices(result.shape)
        result[present & (xx > size * 0.8) & (yy > size * 0.78)] = 36

    elif recipe_id == 426:  # Two coherent red regions, cream eyes, dark pupils.
        prototypes = np.array([
            (255, 255, 255), (83, 14, 15), (123, 22, 25),
            (249, 210, 209), (15, 15, 15), (245, 81, 27),
        ], dtype=np.float32)
        labels = ((source.astype(np.float32)[:, :, None, :] - prototypes) ** 2).sum(axis=3).argmin(axis=2)
        yy, xx = np.indices(labels.shape)
        eye_region = (((xx - 155) / 72) ** 2 + ((yy - 193) / 60) ** 2 <= 1)
        eye_region |= (((xx - 355) / 72) ** 2 + ((yy - 189) / 60) ** 2 <= 1)
        labels[(labels == 3) & ~eye_region] = 0
        fractions = np.stack([cover(labels == index, size) for index in range(6)])
        present = 1 - fractions[0] >= 0.46
        dominant = fractions[1:].argmax(axis=0) + 1
        colors = np.array([-1, 147, 142, 113, 189, 13], dtype=np.int16)
        result[present] = colors[dominant[present]]
        result[result == 189] = 113
        result[result == 13] = 142
        art = Image.fromarray(result.astype(np.int32), 'I')
        draw = ImageDraw.Draw(art)
        def owl_point(x, y):
            return (round(x * (size - 1) / 511), round(y * (size - 1) / 511))
        if size == 24:
            pupils = ((7, 8, 8, 9), (16, 8, 17, 9))
        else:
            pupils = [(*owl_point(x1, y1), *owl_point(x2, y2))
                      for x1, y1, x2, y2 in ((129, 173, 179, 214), (329, 169, 381, 210))]
        for box in pupils:
            draw.ellipse(box, fill=189)
        draw.polygon([owl_point(x, y) for x, y in ((253, 211), (280, 248), (258, 302), (222, 255))], fill=13)
        result = np.asarray(art, dtype=np.int16).copy()

    elif recipe_id == 428:  # Keep the blue animal, omit the cast shadow.
        blue = cover((b > r + 20) & (b > g + 10) & (g > r + 15), size)
        result[blue >= 0.42] = 287
        art = Image.fromarray(result.astype(np.int32), 'I')
        draw = ImageDraw.Draw(art)
        cx = round(80 * (size - 1) / 511)
        cy = round(246 * (size - 1) / 511)
        outer = max(1, round(24 * size / 512))
        inner = max(1, round(16 * size / 512))
        if outer > inner:
            left, top = cx - outer // 2, cy - outer // 2
            draw.ellipse((left, top, left + outer - 1, top + outer - 1), fill=184)
        left, top = cx - inner // 2, cy - inner // 2
        draw.rectangle((left, top, left + inner - 1, top + inner - 1), fill=189)
        result = np.asarray(art, dtype=np.int16).copy()

    elif recipe_id == 436:
        prototypes = np.array([(255, 255, 255), (255, 245, 0),
                               (255, 180, 65), (140, 194, 60),
                               (40, 40, 35)], dtype=np.float32)
        labels = ((source.astype(np.float32)[:, :, None, :] - prototypes) ** 2).sum(3).argmin(2)
        fractions = np.stack([cover(labels == i, size) for i in range(5)])
        present = 1 - fractions[0] >= .45
        colors = np.array([-1, 246, 236, 42, 188], dtype=np.int16)
        dominant = fractions[1:].argmax(0) + 1
        result[present] = colors[dominant[present]]
        result[present & (fractions[4] >= (.24 if size == 24 else .28))] = 188

    elif recipe_id == 447:
        prototypes = np.array([(255, 255, 255), (38, 216, 38),
                               (35, 145, 40), (12, 66, 17),
                               (113, 67, 39), (15, 24, 16)], dtype=np.float32)
        labels = ((source.astype(np.float32)[:, :, None, :] - prototypes) ** 2).sum(3).argmin(2)
        labels[(r > g * 1.3) & (r > b * 1.4) & (r < 180)] = 4
        fractions = np.stack([cover(labels == i, size) for i in range(6)])
        present = 1 - fractions[0] >= .43
        colors = np.array([-1, 30, 33, 40, 270, 189], dtype=np.int16)
        dominant = fractions[1:].argmax(0) + 1
        result[present] = colors[dominant[present]]
        result[present & (fractions[5] >= .25)] = 189

    elif recipe_id == 468:
        prototypes = np.array([(255, 255, 255), (245, 145, 0),
                               (25, 166, 46), (15, 20, 15)], dtype=np.float32)
        labels = ((source.astype(np.float32)[:, :, None, :] - prototypes) ** 2).sum(3).argmin(2)
        fractions = np.stack([cover(labels == i, size) for i in range(4)])
        present = 1 - fractions[0] >= .46
        # The white reflection belongs inside the fruit, not a cutout.
        holes = Image.fromarray((~present).astype(np.uint8) * 255, 'L').copy()
        ImageDraw.floodfill(holes, (0, 0), 0)
        reflection = np.asarray(holes) == 255
        present |= reflection
        colors = np.array([-1, 167, 33, 189], dtype=np.int16)
        dominant = fractions[1:].argmax(0) + 1
        result[present] = colors[dominant[present]]
        padded = np.pad(present, 1)
        interior = (padded[1:-1, 1:-1] & padded[:-2, 1:-1] & padded[2:, 1:-1]
                    & padded[1:-1, :-2] & padded[1:-1, 2:])
        result[present & ~interior] = 189
        result[present & (fractions[3] >= .22)] = 189
        result[reflection] = 0

    elif recipe_id == 498:
        prototypes = np.array([(255, 255, 255), (250, 154, 253),
                               (255, 255, 0), (0, 0, 0)], dtype=np.float32)
        labels = ((source.astype(np.float32)[:, :, None, :] - prototypes) ** 2).sum(3).argmin(2)
        white = Image.fromarray((labels == 0).astype(np.uint8) * 255, 'L').copy()
        ImageDraw.floodfill(white, (0, 0), 0)
        labels[np.asarray(white) == 255] = 4
        fractions = np.stack([cover(labels == i, size) for i in range(5)])
        present = (1 - fractions[0] >= .44) | (fractions[3] >= .22)
        colors = np.array([-1, 244, 246, 189, 184], dtype=np.int16)
        dominant = fractions[1:].argmax(0) + 1
        result[present] = colors[dominant[present]]
        result[present & (fractions[3] >= (.18 if size == 24 else .24))] = 189

    elif recipe_id == 505:
        prototypes = np.array([(255, 255, 255), (255, 215, 0),
                               (225, 216, 166), (53, 57, 59)], dtype=np.float32)
        labels = ((source.astype(np.float32)[:, :, None, :] - prototypes) ** 2).sum(3).argmin(2)
        fractions = np.stack([cover(labels == i, size) for i in range(4)])
        fractions = (fractions + fractions[:, :, ::-1]) / 2
        present = 1 - fractions[0] >= .45
        colors = np.array([-1, 246, 210, 188], dtype=np.int16)
        dominant = fractions[1:].argmax(0) + 1
        result[present] = colors[dominant[present]]
        result[present & (fractions[3] >= (.22 if size == 24 else .28))] = 188
        if size == 24:
            result[:4] = -1
            art = Image.fromarray(result.astype(np.int32), 'I')
            draw = ImageDraw.Draw(art)
            draw.line([(9, 1), (11, 4)], fill=188)
            draw.line([(14, 1), (12, 4)], fill=188)
            draw.line([(11, 0), (11, 4)], fill=188)
            draw.line([(12, 0), (12, 4)], fill=188)
            for left in (6, 15):
                draw.rectangle((left, 10, left + 2, 11), fill=246)
                draw.line([(left, 11), (left, 10), (left + 2, 10), (left + 2, 11)], fill=188)
            # Separate the nostrils instead of merging them into a bar.
            draw.rectangle((10, 13, 13, 14), fill=210)
            draw.point((10, 15), fill=188)
            draw.point((13, 15), fill=188)
            result = np.asarray(art, dtype=np.int16).copy()

    else:
        raise ValueError(f"No reviewed recipe for image {recipe_id}")

    return result


def flat_classes(source: np.ndarray, size: int, profile: dict) -> np.ndarray:
    """Reusable exclusive color regions, enclosed whites, and ink coverage."""
    profile = {**profile, **profile.get('sizes', {}).get(str(size), {})}
    if 'grid' in profile:
        grid = np.asarray(profile['grid'], dtype=np.int16)
        if grid.shape != (size, size) or grid.min() < -1 or grid.max() >= len(PALETTE):
            raise ValueError('Invalid hand-authored palette grid')
        return grid.copy()
    prototypes = np.array(profile['rgb'], dtype=np.float32)
    labels = ((source.astype(np.float32)[:, :, None, :] - prototypes) ** 2).sum(3).argmin(2)
    # Neutral antialias pixels on black/white edges must not become a
    # saturated accent merely because its RGB distance is smaller.
    neutral_classes = np.flatnonzero(np.ptp(prototypes, axis=1) < 10)
    if len(neutral_classes) >= 2:
        neutral_pixels = np.ptp(source.astype(np.float32), axis=2) < 10
        values = source[neutral_pixels].astype(np.float32)
        if len(values):
            nearest = ((values[:, None, :] - prototypes[neutral_classes]) ** 2).sum(2).argmin(1)
            labels[neutral_pixels] = neutral_classes[nearest]
    colors = list(profile['indices'])
    if profile.get('enclosed_white') is not None:
        white = Image.fromarray((labels == 0).astype(np.uint8) * 255, 'L').copy()
        width, height = white.size
        for x in range(width):
            for y in (0, height - 1):
                if white.getpixel((x, y)) == 255:
                    ImageDraw.floodfill(white, (x, y), 0)
        for y in range(height):
            for x in (0, width - 1):
                if white.getpixel((x, y)) == 255:
                    ImageDraw.floodfill(white, (x, y), 0)
        labels[np.asarray(white) == 255] = len(colors)
        colors.append(profile['enclosed_white'])
    fractions = np.stack([cover(labels == i, size) for i in range(len(colors))])
    if profile.get('symmetry'):
        fractions = (fractions + fractions[:, :, ::-1]) / 2
    present = 1 - fractions[0] >= profile['coverage']
    ink = profile.get('ink')
    if ink is not None:
        present |= fractions[ink] >= profile['ink_coverage']
    dominant = fractions[1:].argmax(0) + 1
    result = np.full((size, size), -1, dtype=np.int16)
    result[present] = np.array(colors, dtype=np.int16)[dominant[present]]
    if ink is not None:
        result[present & (fractions[ink] >= profile['ink_coverage'])] = colors[ink]
    if profile.get('outline') and ink is not None:
        p = np.pad(present, 1)
        inside = p[1:-1, 1:-1] & p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:]
        result[present & ~inside] = colors[ink]
    for patch in profile.get('patches', []):
        x1, y1, x2, y2 = [round(v * size / 512) for v in patch['rect']]
        region = result[y1:y2 + 1, x1:x2 + 1]
        region[region == patch['from']] = patch['color']
    for stroke in profile.get('strokes', []):
        mask = Image.new('L', (size, size))
        points = [(min(size - 1, round(x * (size - 1) / 511)),
                   min(size - 1, round(y * (size - 1) / 511))) for x, y in stroke['points']]
        ImageDraw.Draw(mask).line(points, fill=255, width=max(1, round(stroke['width'] * size / 512)))
        result[(np.asarray(mask) > 0) & (result >= 0)] = stroke['color']
    if profile.get('ellipses'):
        art = Image.fromarray(result.astype(np.int32), 'I')
        draw = ImageDraw.Draw(art)
        for ellipse in profile['ellipses']:
            box = [int(np.floor(v * size / 512)) if i < 2 else int(np.ceil(v * size / 512)) - 1
                   for i, v in enumerate(ellipse['rect'])]
            box[2] = max(box[0], box[2])
            box[3] = max(box[1], box[3])
            # A three-cell circle becomes a cross. Use an even diameter for
            # tiny filled circles so eyes have rounded corners and a center.
            circle_like = abs((ellipse['rect'][2] - ellipse['rect'][0]) -
                              (ellipse['rect'][3] - ellipse['rect'][1])) <= 2
            if ellipse['color'] == ellipse['outline'] and circle_like:
                for lo, hi in ((0, 2), (1, 3)):
                    diameter = box[hi] - box[lo] + 1
                    if diameter in (3, 5):
                        box[hi] = min(size - 1, box[hi] + 1)
            draw.ellipse(box, fill=ellipse['color'], outline=ellipse['outline'],
                         width=max(1, round(ellipse['width'] * size / 512)))
        result = np.asarray(art, dtype=np.int16).copy()
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


def database():
    connection = sqlite3.connect(DATA / "annotation.sqlite3")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def image_bytes(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def asset(connection, name: str) -> bytes | None:
    row = connection.execute("SELECT content FROM assets WHERE path=?", (name,)).fetchone()
    return row[0] if row else None


def recipe_fingerprint(recipe_id: int, sizes: tuple[int, ...]) -> str:
    digest = hashlib.sha256(Path(__file__).read_bytes())
    digest.update(f"{recipe_id}:{','.join(map(str, sizes))}".encode())
    profile = PROFILES / f'{recipe_id}.json'
    if profile.exists():
        digest.update(profile.read_bytes())
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
    manifest = {
        "recipe_id": recipe_id,
        "sizes": list(sizes),
        "fingerprint": recipe_fingerprint(recipe_id, sizes),
    }
    with database() as connection:
        connection.execute("INSERT OR REPLACE INTO assets VALUES (?, ?)",
                           (f"reviews/recipes/{output.name}", output.read_bytes()))
        connection.execute("INSERT OR REPLACE INTO assets VALUES (?, ?)",
                           (f"reviews/recipes/{output.stem}.json", json.dumps(manifest).encode()))
    return output


def apply(recipe_id: int, sizes: tuple[int, ...], force: bool) -> None:
    preview_file = REVIEWS / f"{recipe_id}-{'-'.join(map(str, sizes))}.png"
    connection = database()
    prefix = f"reviews/recipes/{preview_file.stem}"
    if asset(connection, prefix + ".png") is None:
        raise ValueError(f"Review preview first: {preview_file}")
    manifest = asset(connection, prefix + ".json")
    if manifest is None or json.loads(manifest).get("fingerprint") != recipe_fingerprint(recipe_id, sizes):
        raise ValueError(f"Preview is stale; regenerate and review: {preview_file}")
    for size in sizes:
        sample_id = f"{recipe_id}_{size}"
        row = connection.execute("SELECT record FROM samples WHERE id=?", (sample_id,)).fetchone()
        if row is None:
            raise ValueError(f"Missing sample: {sample_id}")
        record = json.loads(zlib.decompress(row[0]))
        if not force and (record.get("status", "unmodified") != "unmodified" or "corrected_indices" in record):
            print(f"skip {sample_id}: existing annotation or review state")
            continue
        previous_status = record.get("status", "unmodified")
        if previous_status in ("qualified", "unqualified"):
            history = record.get("review_history") or [{
                "from": None, "to": previous_status,
                "reason": record.get("review_reason", ""),
                "timestamp": record.get("reviewed_at"),
            }]
            record["review_history"] = [*history, {
                "from": previous_status, "to": "pending",
                "reason": "AI 修正后重新送审",
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }]
        source = np.asarray(Image.open(DATA / "sources" / f"{sample_id}.png").convert("RGB"))
        indices = classes(source, size, recipe_id)
        flat = indices.ravel().tolist()
        if len(flat) != len(record["indices"]):
            raise ValueError(f"Dimension mismatch: {sample_id}")
        changed = np.asarray(flat) != np.asarray(record["indices"])
        corrected_png = image_bytes(render(indices))
        mask = np.zeros((size, size, 4), dtype=np.uint8)
        mask[:, :, :3] = changed.reshape(size, size, 1).astype(np.uint8) * 255
        mask[:, :, 3] = 255
        mask_png = image_bytes(Image.fromarray(mask, "RGBA"))
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
        record["corrected_indices"] = flat
        record["changed_pixels"] = metadata["changed_pixels"]
        record["status"] = "pending"
        record["annotation_source"] = "ai"
        record.pop("reviewed_at", None)
        record.pop("review_reason", None)
        history = record.get("review_history") or []
        with connection:
            connection.execute("INSERT OR REPLACE INTO images VALUES (?, 'corrected', ?)", (sample_id, corrected_png))
            connection.execute("INSERT OR REPLACE INTO images VALUES (?, 'edit_masks', ?)", (sample_id, mask_png))
            connection.execute("INSERT OR REPLACE INTO metadata VALUES (?, ?)", (sample_id, json.dumps(metadata)))
            connection.execute("""UPDATE samples SET status=?, changed_pixels=?, reviewed_at=?,
                review_reason=?, review_history=?, history_count=?, has_corrected=1, has_meta=1,
                record=? WHERE id=?""", (
                record["status"], record["changed_pixels"], record.get("reviewed_at"),
                record.get("review_reason"), json.dumps(history), len(history),
                zlib.compress(json.dumps(record, separators=(",", ":")).encode(), level=1), sample_id))
        print(f"saved {sample_id}: {metadata['changed_pixels']} changed pixels; pending review")
    connection.close()


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
    REVIEWS = Path(tempfile.gettempdir()) / "pixel_annotation_reviews" / "recipes"
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
