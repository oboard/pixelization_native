use image::{Rgb, RgbImage};

#[derive(Clone, Copy, Debug)]
pub struct SimpleCleanupOptions {
    /// Known teacher lattice pitch in pixels. WuZongWei6 teacher uses 4.
    pub pitch: u32,
    /// RGB Euclidean merge threshold for palette extraction.
    pub merge_threshold: f32,
    /// Optional palette cap after close-color merging.
    pub max_colors: Option<usize>,
    /// Detail-preserving-ish neighborhood smoothing passes.
    pub smooth_passes: usize,
}

impl Default for SimpleCleanupOptions {
    fn default() -> Self {
        Self {
            pitch: 4,
            merge_threshold: 18.0,
            max_colors: None,
            smooth_passes: 2,
        }
    }
}

#[derive(Clone, Debug)]
pub struct SimpleCleanupReport {
    pub cells_w: u32,
    pub cells_h: u32,
    pub palette_size: usize,
}

#[derive(Clone, Copy, Debug)]
struct Cluster {
    repr: [u8; 3],
    count: u32,
}

#[inline]
fn dist2(a: [u8; 3], b: [u8; 3]) -> u32 {
    let dr = i32::from(a[0]) - i32::from(b[0]);
    let dg = i32::from(a[1]) - i32::from(b[1]);
    let db = i32::from(a[2]) - i32::from(b[2]);
    (dr * dr + dg * dg + db * db) as u32
}

#[inline]
fn median_u8(vals: &mut [u8]) -> u8 {
    vals.sort_unstable();
    vals[vals.len() / 2]
}

fn sample_cell_median(img: &RgbImage, x0: u32, y0: u32, pitch: u32) -> [u8; 3] {
    // Sample the centered half of the cell, similar in spirit to ai2pixelart's
    // robust center-window median. For pitch=4 this is a 2x2 core.
    let keep = (pitch / 2).max(1);
    let ox = (pitch - keep) / 2;
    let oy = (pitch - keep) / 2;
    let mut r = Vec::with_capacity((keep * keep) as usize);
    let mut g = Vec::with_capacity((keep * keep) as usize);
    let mut b = Vec::with_capacity((keep * keep) as usize);
    for yy in y0 + oy..y0 + oy + keep {
        for xx in x0 + ox..x0 + ox + keep {
            let p = img.get_pixel(xx.min(img.width() - 1), yy.min(img.height() - 1));
            r.push(p[0]);
            g.push(p[1]);
            b.push(p[2]);
        }
    }
    [median_u8(&mut r), median_u8(&mut g), median_u8(&mut b)]
}

fn extract_palette(cells: &[[u8; 3]], opts: SimpleCleanupOptions) -> Vec<[u8; 3]> {
    use std::collections::HashMap;

    let mut hist: HashMap<[u8; 3], u32> = HashMap::new();
    for &c in cells {
        *hist.entry(c).or_insert(0) += 1;
    }
    let mut colors: Vec<([u8; 3], u32)> = hist.into_iter().collect();
    colors.sort_by_key(|(_, count)| std::cmp::Reverse(*count));

    let limit = opts.max_colors.unwrap_or(usize::MAX);
    let threshold2 = (opts.merge_threshold * opts.merge_threshold).round() as u32;
    let mut clusters: Vec<Cluster> = Vec::new();

    'color: for (color, count) in colors {
        let mut best_i = None;
        let mut best_d = u32::MAX;
        for (i, c) in clusters.iter().enumerate() {
            let d = dist2(color, c.repr);
            if d < best_d {
                best_d = d;
                best_i = Some(i);
            }
        }
        if let Some(i) = best_i {
            if best_d <= threshold2 || clusters.len() >= limit {
                clusters[i].count += count;
                continue 'color;
            }
        }
        clusters.push(Cluster { repr: color, count });
    }

    clusters.sort_by_key(|c| std::cmp::Reverse(c.count));
    clusters.truncate(limit);
    clusters.into_iter().map(|c| c.repr).collect()
}

fn assign_indices(cells: &[[u8; 3]], palette: &[[u8; 3]]) -> Vec<usize> {
    cells
        .iter()
        .map(|&c| {
            palette
                .iter()
                .enumerate()
                .min_by_key(|&(_, &p)| dist2(c, p))
                .map(|(i, _)| i)
                .unwrap_or(0)
        })
        .collect()
}

fn smooth_indices(indices: &mut [usize], raw: &[[u8; 3]], palette: &[[u8; 3]], w: u32, h: u32, passes: usize) {
    if w < 3 || h < 3 || palette.is_empty() {
        return;
    }
    let w_us = w as usize;
    let h_us = h as usize;
    for _ in 0..passes {
        let prev = indices.to_vec();
        for y in 1..h_us - 1 {
            for x in 1..w_us - 1 {
                let idx = y * w_us + x;
                let cur = prev[idx];
                let mut counts = vec![0u8; palette.len()];
                for ny in y - 1..=y + 1 {
                    for nx in x - 1..=x + 1 {
                        if nx == x && ny == y {
                            continue;
                        }
                        counts[prev[ny * w_us + nx]] += 1;
                    }
                }
                let (mode, &n) = counts
                    .iter()
                    .enumerate()
                    .max_by_key(|&(_, &n)| n)
                    .unwrap();
                if mode != cur && n >= 5 {
                    // Guard details: only replace if raw cell is not much closer
                    // to its current palette entry than to neighborhood mode.
                    let d_cur = dist2(raw[idx], palette[cur]);
                    let d_mode = dist2(raw[idx], palette[mode]);
                    if d_mode <= d_cur + 12 * 12 {
                        indices[idx] = mode;
                    }
                }
            }
        }
    }
}

/// Clean a known-pitch pseudo-pixel-art image into true-resolution bitmap art.
pub fn clean_known_pitch(img: &RgbImage, opts: SimpleCleanupOptions) -> (RgbImage, SimpleCleanupReport) {
    let pitch = opts.pitch.max(1);
    let cells_w = img.width() / pitch;
    let cells_h = img.height() / pitch;
    let mut cells = Vec::with_capacity((cells_w * cells_h) as usize);
    for cy in 0..cells_h {
        for cx in 0..cells_w {
            cells.push(sample_cell_median(img, cx * pitch, cy * pitch, pitch));
        }
    }

    let palette = extract_palette(&cells, opts);
    let mut indices = assign_indices(&cells, &palette);
    smooth_indices(&mut indices, &cells, &palette, cells_w, cells_h, opts.smooth_passes);

    let mut out = RgbImage::new(cells_w, cells_h);
    for cy in 0..cells_h {
        for cx in 0..cells_w {
            let idx = indices[(cy * cells_w + cx) as usize];
            out.put_pixel(cx, cy, Rgb(palette[idx]));
        }
    }
    (
        out,
        SimpleCleanupReport {
            cells_w,
            cells_h,
            palette_size: palette.len(),
        },
    )
}
