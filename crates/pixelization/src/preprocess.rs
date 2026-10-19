//! 与上游 `test_pro.py` 一致的宿主侧尺寸预处理。

use anyhow::{Context, Result};
use fast_image_resize as fr;
use image::RgbImage;

/// 先将过大的图片逐次缩小，再将过小的图片逐次放大。
pub fn rescale_into_bounds(mut image: RgbImage) -> Result<RgbImage> {
    while image.width() > 4000 || image.height() > 4000 {
        let width = (image.width() / 2).max(1);
        let height = (image.height() / 2).max(1);
        image = resize_bicubic(image, width, height).context("shrink source image")?;
    }

    while image.width() < 128 || image.height() < 128 {
        let width = image
            .width()
            .checked_mul(2)
            .context("source width overflow")?;
        let height = image
            .height()
            .checked_mul(2)
            .context("source height overflow")?;
        image = resize_bicubic(image, width, height).context("grow source image")?;
    }

    Ok(image)
}

fn resize_bicubic(input: RgbImage, width: u32, height: u32) -> Result<RgbImage> {
    let source = fr::images::Image::from_vec_u8(
        input.width(),
        input.height(),
        input.into_raw(),
        fr::PixelType::U8x3,
    )
    .context("create resize source")?;
    let mut destination = fr::images::Image::new(width, height, fr::PixelType::U8x3);
    fr::Resizer::new()
        .resize(
            &source,
            &mut destination,
            Some(
                &fr::ResizeOptions::new()
                    .resize_alg(fr::ResizeAlg::Convolution(fr::FilterType::CatmullRom)),
            ),
        )
        .context("resize source image")?;
    RgbImage::from_raw(width, height, destination.into_vec()).context("create resized image")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keeps_image_inside_bounds() {
        let image = RgbImage::new(512, 256);
        assert_eq!(rescale_into_bounds(image).unwrap().dimensions(), (512, 256));
    }

    #[test]
    fn shrinks_large_image() {
        let image = RgbImage::new(5000, 256);
        assert_eq!(
            rescale_into_bounds(image).unwrap().dimensions(),
            (2500, 128)
        );
    }

    #[test]
    fn grows_small_image() {
        let image = RgbImage::new(64, 96);
        assert_eq!(rescale_into_bounds(image).unwrap().dimensions(), (128, 192));
    }
}
