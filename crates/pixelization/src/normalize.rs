//! 将像素画无损收缩到最小的最近邻逻辑网格。

use image::RgbImage;

/// 反复寻找保持画布宽高比、且能通过最近邻放大无损还原的最小图片。
pub fn smallest_lossless_grid(image: &RgbImage) -> RgbImage {
    let mut current = image.clone();
    loop {
        let smaller = smallest_lossless_step(&current);
        if smaller.dimensions() == current.dimensions() {
            return current;
        }
        current = smaller;
    }
}

fn smallest_lossless_step(image: &RgbImage) -> RgbImage {
    let (width, height) = image.dimensions();
    let x_changes = horizontal_changes(image);
    let y_changes = vertical_changes(image);
    let common = gcd(width, height);

    for multiplier in 1..=common {
        let logical_width = width / common * multiplier;
        let logical_height = height / common * multiplier;
        if !boundaries_allow(width, logical_width, &x_changes)
            || !boundaries_allow(height, logical_height, &y_changes)
        {
            continue;
        }

        let smaller = resize_nearest(image, logical_width, logical_height);
        let restored = resize_nearest(&smaller, width, height);
        if restored.as_raw() == image.as_raw() {
            return smaller;
        }
    }

    image.clone()
}

fn horizontal_changes(image: &RgbImage) -> Vec<u32> {
    let (width, height) = image.dimensions();
    (1..width)
        .filter(|&x| (0..height).any(|y| image.get_pixel(x - 1, y) != image.get_pixel(x, y)))
        .collect()
}

fn vertical_changes(image: &RgbImage) -> Vec<u32> {
    let (width, height) = image.dimensions();
    (1..height)
        .filter(|&y| (0..width).any(|x| image.get_pixel(x, y - 1) != image.get_pixel(x, y)))
        .collect()
}

fn boundaries_allow(output_length: u32, logical_length: u32, changes: &[u32]) -> bool {
    changes.iter().all(|&boundary| {
        nearest_source_index(boundary - 1, logical_length, output_length)
            != nearest_source_index(boundary, logical_length, output_length)
    })
}

/// Pillow 最近邻缩放使用目标像素中心映射到源像素。
fn nearest_source_index(output_index: u32, source_length: u32, output_length: u32) -> u32 {
    let numerator = (u64::from(output_index) * 2 + 1) * u64::from(source_length);
    ((numerator / (u64::from(output_length) * 2)) as u32).min(source_length - 1)
}

fn resize_nearest(image: &RgbImage, width: u32, height: u32) -> RgbImage {
    if image.dimensions() == (width, height) {
        return image.clone();
    }

    let mut output = RgbImage::new(width, height);
    for y in 0..height {
        let source_y = nearest_source_index(y, image.height(), height);
        for x in 0..width {
            let source_x = nearest_source_index(x, image.width(), width);
            output.put_pixel(x, y, *image.get_pixel(source_x, source_y));
        }
    }
    output
}

fn gcd(mut left: u32, mut right: u32) -> u32 {
    while right != 0 {
        (left, right) = (right, left % right);
    }
    left
}

#[cfg(test)]
mod tests {
    use super::*;
    use image::Rgb;

    #[test]
    fn reduces_uniform_blocks_to_logical_grid() {
        let logical = RgbImage::from_raw(2, 1, vec![255, 0, 0, 0, 0, 255]).unwrap();
        let expanded = resize_nearest(&logical, 8, 4);
        let normalized = smallest_lossless_grid(&expanded);
        assert_eq!(normalized, logical);
    }

    #[test]
    fn keeps_non_reducible_image() {
        let mut image = RgbImage::new(4, 4);
        for y in 0..4 {
            for x in 0..4 {
                image.put_pixel(x, y, Rgb([(x * 31) as u8, (y * 47) as u8, (x + y) as u8]));
            }
        }
        assert_eq!(smallest_lossless_grid(&image), image);
    }

    #[test]
    fn preserves_aspect_ratio() {
        let logical = RgbImage::from_raw(
            3,
            2,
            vec![
                255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 0, 255, 0, 255, 0, 255, 255,
            ],
        )
        .unwrap();
        let expanded = resize_nearest(&logical, 12, 8);
        assert_eq!(smallest_lossless_grid(&expanded), logical);
    }

    #[test]
    fn pillow_center_mapping_matches_expected_indices() {
        let image = RgbImage::from_fn(3, 1, |x, _| Rgb([x as u8, 0, 0]));
        let resized = resize_nearest(&image, 5, 1);
        let indices: Vec<u8> = resized.pixels().map(|pixel| pixel[0]).collect();
        assert_eq!(indices, vec![0, 0, 1, 2, 2]);
    }
}
