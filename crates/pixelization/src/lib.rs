//! CPU-only native Pixelization engine — high-quality true-bitmap pipeline.
//!
//! ```text
//! Input image
//!  ↓  aspect-preserving resize to long_edge * teacher_scale (bicubic)
//!  ↓  normalize: RGB8 → NCHW f32 in [-1, 1]
//!  ↓  ONNX Runtime CPU inference (WuZongWei6 teacher)
//!  ↓  denormalize: NCHW f32 → RGB8
//!  ↓  Rust simple cleanup: 4px teacher cells → 1 bitmap pixel
//! Output true-resolution bitmap RGB PNG
//! ```
//!
//! The output PNG is the final bitmap: no upscale, no ÷4→×4 block expansion.

pub mod cleanup;
mod error;

pub use cleanup::{SimpleCleanupOptions, SimpleCleanupReport};
pub use error::PixelizationError;

use std::{
    path::Path,
    sync::Mutex,
    time::{Duration, Instant},
};

use anyhow::{Context, Result};
use fast_image_resize as fr;
use image::{DynamicImage, Rgb, RgbImage, RgbaImage};
use ndarray::Array4;
use ort::{
    session::{Session, SessionInputValue},
    value::{TensorRef, ValueType},
};

// The upstream generator is always trained at this cell size.
const BEST_CELL_SIZE: u32 = 4;

/// Detailed timings for one high-quality inference pass.
#[derive(Clone, Copy, Debug, Default)]
pub struct PixelizeTimings {
    pub preprocess: Duration,
    pub inference: Duration,
    pub postprocess: Duration,
    pub total: Duration,
}

/// An image-to-pixel-art CPU inference engine backed by ONNX Runtime.
///
/// `Session::run` requires exclusive access; a `Mutex` serialises calls.
/// Create one `Pixelizer` per parallel worker for maximum throughput.
pub struct Pixelizer {
    session: Mutex<Session>,
    input_name: String,
}

impl Pixelizer {
    /// Load an ONNX model using ONNX Runtime's CPU execution provider.
    /// Thread count is set to the runtime default (usually all physical cores).
    pub fn load(path: impl AsRef<Path>) -> Result<Self> {
        Self::load_with_threads(path, 0)
    }

    /// Load an ONNX model and set the ONNX Runtime intra-op CPU thread count.
    ///
    /// `threads = 0` keeps the runtime default.
    pub fn load_with_threads(path: impl AsRef<Path>, threads: usize) -> Result<Self> {
        let path = path.as_ref();
        let session = Session::builder()
            .map_err(|e| anyhow::anyhow!("create ORT session builder: {e}"))?
            .with_intra_threads(threads)
            .map_err(|e| anyhow::anyhow!("set intra-op threads: {e}"))?
            .with_inter_threads(1)
            .map_err(|e| anyhow::anyhow!("set inter-op threads: {e}"))?
            .commit_from_file(path)
            .map_err(|e| anyhow::anyhow!("load ONNX model '{}': {e}", path.display()))?;

        let n_inputs = session.inputs().len();
        if n_inputs != 1 {
            return Err(PixelizationError::InvalidInputCount(n_inputs).into());
        }
        let input = &session.inputs()[0];
        let ValueType::Tensor { shape, .. } = input.dtype() else {
            return Err(PixelizationError::InvalidModelInput(Vec::new()).into());
        };
        let dims = shape.to_vec();
        if dims.len() != 4 {
            return Err(PixelizationError::InvalidModelInput(dims).into());
        }
        // Support both static (dims[i] > 0) and dynamic (dims[i] <= 0) shapes
        // dim[0] can be 1 (static batch) or -1 (dynamic batch)
        // dim[1] must be 3 (RGB channels)
        if dims[1] != 3 {
            return Err(PixelizationError::UnsupportedInputShape(dims).into());
        }

        Ok(Self {
            input_name: input.name().to_owned(),
            session: Mutex::new(session),
        })
    }

    /// High-quality true-bitmap pipeline:
    ///
    /// 1. Resize source to `long_edge * teacher_scale` while preserving aspect.
    /// 2. Run the WuZongWei6 teacher ONNX at that high-resolution lattice.
    /// 3. Collapse known 4px teacher cells using the Rust simple cleanup pass.
    /// 4. Return the true-resolution bitmap (no upscale).
    pub fn process_bitmap_timed(
        &self,
        image: &DynamicImage,
        long_edge: u32,
        teacher_scale: u32,
        cleanup_options: cleanup::SimpleCleanupOptions,
    ) -> Result<(DynamicImage, PixelizeTimings, cleanup::SimpleCleanupReport)> {
        if long_edge == 0 || teacher_scale == 0 {
            return Err(PixelizationError::EmptyGrid.into());
        }
        let teacher_long_edge = long_edge
            .checked_mul(teacher_scale)
            .ok_or(PixelizationError::EmptyGrid)?;
        if teacher_long_edge % BEST_CELL_SIZE != 0 {
            return Err(PixelizationError::EmptyGrid.into());
        }

        let total_start = Instant::now();
        let preprocess_start = Instant::now();
        let source = image.to_rgba8();
        let (target_w, target_h) =
            aspect_dims(source.width(), source.height(), teacher_long_edge)?;
        let model_input = resize_rgba_bicubic(&source, target_w, target_h)?;
        let nchw = rgba_to_normalized_nchw(&model_input);
        let preprocess = preprocess_start.elapsed();

        let inference_start = Instant::now();
        let output_tensor = self.infer(nchw)?;
        let inference = inference_start.elapsed();

        let postprocess_start = Instant::now();
        let pseudo = tensor_to_rgb(output_tensor)?;
        let (cleaned, report) = cleanup::clean_known_pitch(&pseudo, cleanup_options);
        let postprocess = postprocess_start.elapsed();
        let total = total_start.elapsed();

        Ok((
            DynamicImage::ImageRgb8(cleaned),
            PixelizeTimings {
                preprocess,
                inference,
                postprocess,
                total,
            },
            report,
        ))
    }

    fn infer(&self, input: Array4<f32>) -> Result<ndarray::ArrayD<f32>> {
        let tensor = TensorRef::from_array_view(&input)
            .map_err(|e| anyhow::anyhow!("build input tensor: {e}"))?;
        let mut session = self
            .session
            .lock()
            .map_err(|_| anyhow::anyhow!("ORT session mutex poisoned"))?;
        let outputs = session
            .run(ort::inputs![self.input_name.as_str() => SessionInputValue::from(tensor)])
            .map_err(|e| anyhow::anyhow!("ORT inference: {e}"))?;
        if outputs.len() == 0 {
            return Err(PixelizationError::MissingModelOutput.into());
        }
        let (shape, data) = outputs[0]
            .try_extract_tensor::<f32>()
            .map_err(|e| anyhow::anyhow!("extract f32 output: {e}"))?;
        ndarray::ArrayD::from_shape_vec(shape.to_ixdyn(), data.to_vec())
            .context("copy output tensor to ndarray")
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn aspect_dims(w: u32, h: u32, long_edge: u32) -> Result<(u32, u32)> {
    if w == 0 || h == 0 || long_edge == 0 || long_edge % BEST_CELL_SIZE != 0 {
        return Err(PixelizationError::EmptyGrid.into());
    }
    let (mut tw, mut th) = if w >= h {
        let short = ((h as f64 * long_edge as f64 / w as f64) / BEST_CELL_SIZE as f64).round()
            as u32
            * BEST_CELL_SIZE;
        (long_edge, short.max(BEST_CELL_SIZE))
    } else {
        let short = ((w as f64 * long_edge as f64 / h as f64) / BEST_CELL_SIZE as f64).round()
            as u32
            * BEST_CELL_SIZE;
        (short.max(BEST_CELL_SIZE), long_edge)
    };
    tw = (tw / BEST_CELL_SIZE) * BEST_CELL_SIZE;
    th = (th / BEST_CELL_SIZE) * BEST_CELL_SIZE;
    if tw == 0 || th == 0 {
        return Err(PixelizationError::EmptyGrid.into());
    }
    Ok((tw, th))
}

/// Convert RGBA8 HWC to normalized NCHW f32 in one pass.
/// Normalization: `(x / 255.0 − 0.5) / 0.5`  ⟺  `x / 127.5 − 1.0`.
pub(crate) fn rgba_to_normalized_nchw(image: &RgbaImage) -> Array4<f32> {
    let (w, h) = image.dimensions();
    let plane = (w * h) as usize;
    let mut data = vec![0.0f32; plane * 3];
    for (i, pixel) in image.pixels().enumerate() {
        data[i] = f32::from(pixel[0]) / 127.5 - 1.0;
        data[plane + i] = f32::from(pixel[1]) / 127.5 - 1.0;
        data[2 * plane + i] = f32::from(pixel[2]) / 127.5 - 1.0;
    }
    Array4::from_shape_vec((1, 3, h as usize, w as usize), data).expect("known shape")
}

/// Denormalize NCHW f32 output `[-1, 1]` → `RGB8` with clamp.
fn tensor_to_rgb(tensor: ndarray::ArrayD<f32>) -> Result<RgbImage> {
    let sh = tensor.shape();
    if sh.len() != 4 || sh[0] != 1 || sh[1] != 3 {
        return Err(PixelizationError::InvalidModelOutput(sh.to_vec()).into());
    }
    let (h, w) = (sh[2] as u32, sh[3] as u32);
    let plane = (w * h) as usize;
    let vals = tensor.as_slice().context("model output not contiguous")?;
    let mut img = RgbImage::new(w, h);
    for (i, px) in img.pixels_mut().enumerate() {
        let f = |v: f32| ((v + 1.0) * 0.5 * 255.0).clamp(0.0, 255.0) as u8;
        *px = Rgb([f(vals[i]), f(vals[plane + i]), f(vals[2 * plane + i])]);
    }
    Ok(img)
}

fn resize_rgba_bicubic(input: &RgbaImage, w: u32, h: u32) -> Result<RgbaImage> {
    if input.width() == w && input.height() == h {
        return Ok(input.clone());
    }
    let src = fr::images::Image::from_vec_u8(
        input.width(),
        input.height(),
        input.as_raw().to_vec(),
        fr::PixelType::U8x4,
    )
    .context("bicubic resize src")?;
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
        .context("bicubic resize")?;
    RgbaImage::from_raw(w, h, dst.into_vec()).context("bicubic resize output")
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn nchw_normalization_layout_and_values() {
        let img = RgbaImage::from_raw(1, 1, vec![0u8, 127, 255, 42]).unwrap();
        let data = rgba_to_normalized_nchw(&img);
        assert_eq!(data.shape(), &[1, 3, 1, 1]);
        assert!((data[[0, 0, 0, 0]] - (-1.0_f32)).abs() < 1e-6, "R=-1 expected");
        let expected_g = 127.0_f32 / 127.5 - 1.0;
        assert!((data[[0, 1, 0, 0]] - expected_g).abs() < 1e-5, "G mismatch");
        assert!((data[[0, 2, 0, 0]] - 1.0_f32).abs() < 1e-5, "B=1 expected");
    }

    #[test]
    fn nchw_layout_is_channel_first() {
        let mut img = RgbaImage::new(2, 2);
        img.put_pixel(0, 0, image::Rgba([10, 20, 30, 255]));
        img.put_pixel(1, 0, image::Rgba([40, 50, 60, 255]));
        img.put_pixel(0, 1, image::Rgba([70, 80, 90, 255]));
        img.put_pixel(1, 1, image::Rgba([100, 110, 120, 255]));
        let data = rgba_to_normalized_nchw(&img);
        assert_eq!(data.shape(), &[1, 3, 2, 2]);
        assert!((data[[0, 0, 0, 0]] - (10.0_f32 / 127.5 - 1.0)).abs() < 1e-5);
        assert!((data[[0, 0, 0, 1]] - (40.0_f32 / 127.5 - 1.0)).abs() < 1e-5);
    }

    #[test]
    fn tensor_to_rgb_roundtrip() {
        let mut img = RgbaImage::new(2, 2);
        img.put_pixel(0, 0, image::Rgba([0, 128, 255, 255]));
        img.put_pixel(1, 0, image::Rgba([64, 192, 32, 255]));
        img.put_pixel(0, 1, image::Rgba([255, 0, 128, 255]));
        img.put_pixel(1, 1, image::Rgba([100, 100, 100, 255]));
        let nchw = rgba_to_normalized_nchw(&img);
        let dyn_arr = nchw.into_dyn();
        let recovered = tensor_to_rgb(dyn_arr).unwrap();
        for (orig, rec) in img.pixels().zip(recovered.pixels()) {
            for c in 0..3 {
                let diff = (i32::from(orig[c]) - i32::from(rec[c])).unsigned_abs();
                assert!(diff <= 1, "channel {c}: orig={} rec={}", orig[c], rec[c]);
            }
        }
    }

    #[test]
    fn aspect_dims_landscape() {
        let (tw, th) = aspect_dims(356, 260, 512).unwrap();
        assert_eq!(tw, 512);
        assert_eq!(th, 372);
    }

    #[test]
    fn aspect_dims_portrait() {
        let (tw, th) = aspect_dims(300, 600, 128).unwrap();
        assert_eq!(th, 128);
        assert!(tw <= 128);
        assert_eq!(tw % 4, 0);
    }

    #[test]
    fn aspect_dims_rejects_zero() {
        assert!(aspect_dims(0, 100, 128).is_err());
        assert!(aspect_dims(100, 100, 0).is_err());
    }
}
