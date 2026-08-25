//! Host-side preprocessing helpers matching `test_pro.py`'s `rescale()` function.
//!
//! Rules (verbatim from upstream):
//!   * While `max(W, H) > 4000`: halve by BICUBIC.
//!   * While `min(W, H) < 128`:  double by BICUBIC.

use anyhow::{Context, Result};
use fast_image_resize as fr;
use image::RgbaImage;

/// Rescale an RGBA image so that both dimensions are in `[128, 4000]`.
///
/// Uses BICUBIC (CatmullRom) for all intermediate steps, matching
/// `Image.BICUBIC` in `test_pro.py:rescale`.
pub fn rescale_into_bounds(mut img: RgbaImage) -> Result<RgbaImage> {
    loop {
        let (w, h) = img.dimensions();
        if w > 4000 || h > 4000 {
            let nw = (w / 2).max(1);
            let nh = (h / 2).max(1);
            img = bicubic_rgba(img, nw, nh).context("rescale: shrink step")?;
        } else if w < 128 || h < 128 {
            let nw = w * 2;
            let nh = h * 2;
            img = bicubic_rgba(img, nw, nh).context("rescale: grow step")?;
        } else {
            break;
        }
    }
    Ok(img)
}

fn bicubic_rgba(input: RgbaImage, w: u32, h: u32) -> Result<RgbaImage> {
    let (iw, ih) = input.dimensions();
    let src = fr::images::Image::from_vec_u8(iw, ih, input.into_raw(), fr::PixelType::U8x4)
        .context("rescale src")?;
    let mut dst = fr::images::Image::new(w, h, fr::PixelType::U8x4);
    fr::Resizer::new()
        .resize(
            &src,
            &mut dst,
            Some(
                &fr::ResizeOptions::new()
                    .resize_alg(fr::ResizeAlg::Convolution(fr::FilterType::CatmullRom)),
            ),
        )
        .context("rescale resize")?;
    RgbaImage::from_raw(w, h, dst.into_vec()).context("rescale output")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn already_in_bounds_unchanged() {
        let img = RgbaImage::from_pixel(512, 512, image::Rgba([0, 0, 0, 255]));
        let out = rescale_into_bounds(img).unwrap();
        assert_eq!(out.dimensions(), (512, 512));
    }

    #[test]
    fn wide_image_shrinks() {
        // Slightly over the limit to trigger exactly one shrink step.
        let img = RgbaImage::from_pixel(5001, 257, image::Rgba([0, 0, 0, 255]));
        let out = rescale_into_bounds(img).unwrap();
        assert!(out.width() <= 4000 && out.height() <= 4000);
        assert!(out.width() >= 128 && out.height() >= 128);
    }

    #[test]
    fn tall_image_shrinks() {
        let img = RgbaImage::from_pixel(257, 5001, image::Rgba([0, 0, 0, 255]));
        let out = rescale_into_bounds(img).unwrap();
        assert!(out.width() <= 4000 && out.height() <= 4000);
    }

    #[test]
    fn tiny_image_grows() {
        let img = RgbaImage::from_pixel(50, 50, image::Rgba([0, 0, 0, 255]));
        let out = rescale_into_bounds(img).unwrap();
        assert!(out.width() >= 128 && out.height() >= 128);
    }

    #[test]
    fn exactly_at_lower_bound_unchanged() {
        let img = RgbaImage::from_pixel(128, 256, image::Rgba([0, 0, 0, 255]));
        let out = rescale_into_bounds(img).unwrap();
        assert_eq!(out.dimensions(), (128, 256));
    }

    #[test]
    fn exactly_at_upper_bound_unchanged() {
        let img = RgbaImage::from_pixel(4000, 3000, image::Rgba([0, 0, 0, 255]));
        let out = rescale_into_bounds(img).unwrap();
        assert_eq!(out.dimensions(), (4000, 3000));
    }
}
