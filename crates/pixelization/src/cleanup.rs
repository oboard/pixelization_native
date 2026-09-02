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
    /// Align nominal teacher lattice boundaries to local Sobel edge-energy peaks.
    /// This is the useful grid-refinement stage adapted from perfectPixel.
    pub refine_grid: bool,
    /// Search radius around each nominal grid boundary, in teacher pixels.
    pub refine_radius: u32,
}

impl Default for SimpleCleanupOptions {
    fn default() -> Self {
        Self {
            pitch: 4,
            merge_threshold: 60.0,
            max_colors: Some(20),
            smooth_passes: 2,
            refine_grid: false,
            refine_radius: 1,
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

fn sample_cell_median(img: &RgbImage, x0: u32, y0: u32, x1: u32, y1: u32) -> [u8; 3] {
    // Center-window median avoids teacher's anti-aliased/interpolated grid edge.
    // The boundaries may be Sobel-refined, so derive the sample window per cell.
    let width = (x1 - x0).max(1);
    let height = (y1 - y0).max(1);
    let keep_w = (width / 2).max(1);
    let keep_h = (height / 2).max(1);
    let sx = x0 + (width - keep_w) / 2;
    let sy = y0 + (height - keep_h) / 2;
    let mut r = Vec::with_capacity((keep_w * keep_h) as usize);
    let mut g = Vec::with_capacity((keep_w * keep_h) as usize);
    let mut b = Vec::with_capacity((keep_w * keep_h) as usize);
    for yy in sy..sy + keep_h {
        for xx in sx..sx + keep_w {
            let p = img.get_pixel(xx.min(img.width() - 1), yy.min(img.height() - 1));
            r.push(p[0]);
            g.push(p[1]);
            b.push(p[2]);
        }
    }
    [median_u8(&mut r), median_u8(&mut g), median_u8(&mut b)]
}

/// Return vertical and horizontal Sobel energy projections. This is a direct,
/// allocation-light Rust adaptation of perfectPixel's `refine_grids` stage.
fn sobel_edge_projections(img: &RgbImage) -> (Vec<u64>, Vec<u64>) {
    let w = img.width() as usize;
    let h = img.height() as usize;
    let mut gray = vec![0i32; w * h];
    for y in 0..h {
        for x in 0..w {
            let p = img.get_pixel(x as u32, y as u32);
            gray[y * w + x] = (299 * i32::from(p[0]) + 587 * i32::from(p[1]) + 114 * i32::from(p[2])) / 1000;
        }
    }
    let mut vertical = vec![0u64; w];
    let mut horizontal = vec![0u64; h];
    if w < 3 || h < 3 {
        return (vertical, horizontal);
    }
    for y in 1..h - 1 {
        for x in 1..w - 1 {
            let tl = gray[(y - 1) * w + x - 1];
            let tc = gray[(y - 1) * w + x];
            let tr = gray[(y - 1) * w + x + 1];
            let ml = gray[y * w + x - 1];
            let mr = gray[y * w + x + 1];
            let bl = gray[(y + 1) * w + x - 1];
            let bc = gray[(y + 1) * w + x];
            let br = gray[(y + 1) * w + x + 1];
            let gx = -tl + tr - 2 * ml + 2 * mr - bl + br;
            let gy = -tl - 2 * tc - tr + bl + 2 * bc + br;
            vertical[x] += gx.unsigned_abs() as u64;
            horizontal[y] += gy.unsigned_abs() as u64;
        }
    }
    (vertical, horizontal)
}

fn refine_axis(length: u32, pitch: u32, radius: u32, energy: &[u64]) -> Vec<u32> {
    let cells = length / pitch;
    let mut coords = Vec::with_capacity(cells as usize + 1);
    coords.push(0);
    for cell in 1..cells {
        let nominal = cell * pitch;
        let lo = nominal.saturating_sub(radius).max(coords.last().copied().unwrap_or(0) + 1);
        let hi = (nominal + radius).min(length.saturating_sub(1));
        let mut best = nominal;
        let mut best_energy = 0;
        for x in lo..=hi {
            let score = energy[x as usize];
            if score > best_energy {
                best_energy = score;
                best = x;
            }
        }
        coords.push(best);
    }
    coords.push(length);
    coords
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
    let (x_coords, y_coords) = if opts.refine_grid {
        let (vertical_energy, horizontal_energy) = sobel_edge_projections(img);
        (
            refine_axis(cells_w * pitch, pitch, opts.refine_radius, &vertical_energy),
            refine_axis(cells_h * pitch, pitch, opts.refine_radius, &horizontal_energy),
        )
    } else {
        (
            (0..=cells_w).map(|i| i * pitch).collect(),
            (0..=cells_h).map(|i| i * pitch).collect(),
        )
    };
    let mut cells = Vec::with_capacity((cells_w * cells_h) as usize);
    for cy in 0..cells_h {
        for cx in 0..cells_w {
            cells.push(sample_cell_median(
                img,
                x_coords[cx as usize],
                y_coords[cy as usize],
                x_coords[cx as usize + 1],
                y_coords[cy as usize + 1],
            ));
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
