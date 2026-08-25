//! CPU-only native Pixelization engine.
//!
//! Replicates the exact `test_pro.py` geometry pipeline:
//!
//! ```text
//! Input image
//!  ↓  rescale: BICUBIC halve/double to keep both dims in [128, 4000]
//!  ↓  resize: BICUBIC to (W//cell_size)*4 × (H//cell_size)*4
//!  ↓  center-crop: snap to multiple of 4
//!  ↓  normalize: RGB8 → NCHW f32 in [-1, 1]
//!  ↓  ONNX Runtime CPU inference
//!  ↓  denormalize: NCHW f32 → RGB8 (clamp then cast)
//!  ↓  nearest-neighbor ÷4: collapse 4-px lattice cells to 1 px
//!  ↓  nearest-neighbor ×cell_size: each logical cell → cell_size px
//!  ↓  alpha compositing (original alpha plane, same geometry)
//! Output pixel-art RGBA
//! ```
//!
//! Final nearest-neighbor resize is always used; bilinear/bicubic are
//! forbidden for the pixel-grid stage.

mod error;
pub mod preprocess;

pub use error::PixelizationError;

use std::{path::Path, sync::Mutex, time::{Duration, Instant}};

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

/// Pixel-grid controls applied outside the neural network.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PixelizeOptions {
    /// Final pixel cell width/height in the output image. Must be ≥ 1.
    ///
    /// The network always runs at a 4-px lattice. Larger values produce a coarser mosaic.
    pub cell_size: u32,
}

impl Default for PixelizeOptions {
    fn default() -> Self {
        Self { cell_size: 4 }
    }
}

/// Detailed timings for one low-resolution inference pass.
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

    /// Model's static input size as `(width, height)`.
    ///
    /// Returns `(0, 0)` for dynamic-shape models (the actual size depends on input).
    #[inline]
    pub fn input_size(&self) -> (u32, u32) {
        // Dynamic-shape model - size is determined at runtime
        (0, 0)
    }

    /// Pixelize one image.
    ///
    /// Alpha is preserved: it travels through the same nearest-neighbor grid
    /// geometry as the RGB channels and is composited onto the output.
    pub fn process(&self, image: &DynamicImage, options: PixelizeOptions) -> Result<DynamicImage> {
        if options.cell_size == 0 {
            return Err(PixelizationError::InvalidCellSize(0).into());
        }

        let source = image.to_rgba8();

        // Step 1 – rescale to [128, 4000] (mirrors test_pro.rescale()).
        let source = preprocess::rescale_into_bounds(source)?;

        // Step 2 – resize to (W//cell_size)*BEST × (H//cell_size)*BEST via BICUBIC.
        let (sw, sh) = source.dimensions();
        let target_w = (sw / options.cell_size) * BEST_CELL_SIZE;
        let target_h = (sh / options.cell_size) * BEST_CELL_SIZE;
        if target_w == 0 || target_h == 0 {
            return Err(PixelizationError::EmptyGrid.into());
        }
        let resized = resize_rgba_bicubic(&source, target_w, target_h)?;

        // Step 3 – center-crop to nearest multiple of 4 (mirrors test_pro.process()).
        let (rw, rh) = resized.dimensions();
        let crop_w = (rw / 4) * 4;
        let crop_h = (rh / 4) * 4;
        if crop_w == 0 || crop_h == 0 {
            return Err(PixelizationError::EmptyGrid.into());
        }
        let cx = (rw - crop_w) / 2;
        let cy = (rh - crop_h) / 2;
        let cropped = image::imageops::crop_imm(&resized, cx, cy, crop_w, crop_h).to_image();

        // Step 4 – NCHW f32 normalization, inference, denormalization.
        // Note: Dynamic-shape model accepts any size divisible by 4.
        let nchw = rgba_to_normalized_nchw(&cropped);
        let output_tensor = self.infer(nchw)?;
        let generated = tensor_to_rgb(output_tensor)?;

        // Step 5 – nearest-neighbor ÷BEST_CELL_SIZE (collapse lattice cells).
        let grid_w = crop_w / BEST_CELL_SIZE;
        let grid_h = crop_h / BEST_CELL_SIZE;
        let grid = resize_rgb_nearest(&generated, grid_w, grid_h)?;

        // Step 6 – nearest-neighbor ×cell_size (expand to final cell size).
        let out_w = grid_w * options.cell_size;
        let out_h = grid_h * options.cell_size;
        let rgb = resize_rgb_nearest(&grid, out_w, out_h)?;

        // Step 7 – alpha: extract, nearest ÷BEST, nearest ×cell_size.
        let alpha = extract_alpha(&cropped);
        let alpha = resize_gray_nearest(&alpha, grid_w, grid_h)?;
        let alpha = resize_gray_nearest(&alpha, out_w, out_h)?;

        // Step 8 – composite.
        let mut output = RgbaImage::new(out_w, out_h);
        for (x, y, pixel) in output.enumerate_pixels_mut() {
            let c = rgb.get_pixel(x, y);
            *pixel = image::Rgba([c[0], c[1], c[2], alpha.get_pixel(x, y)[0]]);
        }
        Ok(DynamicImage::ImageRgba8(output))
    }

    /// Pixelize using an explicit square neural-network input resolution.
    ///
    /// This is intended for low-resolution pixel-art experiments where the final
    /// pixel-art canvas is itself small (for example 128×128, 56×56, or 32×32).
    /// The input image is first bicubic-resized to `resolution × resolution`, the
    /// unchanged FP32 ONNX model is run at that size, then the model output is
    /// nearest-neighbor downsampled by the trained 4-px lattice and nearest-neighbor
    /// upsampled back to `resolution × resolution`.
    pub fn process_lowres_square_timed(
        &self,
        image: &DynamicImage,
        resolution: u32,
    ) -> Result<(DynamicImage, PixelizeTimings)> {
        if resolution == 0 || resolution % BEST_CELL_SIZE != 0 {
            return Err(PixelizationError::EmptyGrid.into());
        }

        let total_start = Instant::now();
        let preprocess_start = Instant::now();
        let source = image.to_rgba8();
        let model_input = resize_rgba_bicubic(&source, resolution, resolution)?;
        let nchw = rgba_to_normalized_nchw(&model_input);
        let preprocess = preprocess_start.elapsed();

        let inference_start = Instant::now();
        let output_tensor = self.infer(nchw)?;
        let inference = inference_start.elapsed();

        let postprocess_start = Instant::now();
        let generated = tensor_to_rgb(output_tensor)?;
        let grid_w = resolution / BEST_CELL_SIZE;
        let grid_h = resolution / BEST_CELL_SIZE;
        let grid = resize_rgb_nearest(&generated, grid_w, grid_h)?;
        let rgb = resize_rgb_nearest(&grid, resolution, resolution)?;

        let alpha = extract_alpha(&model_input);
        let alpha = resize_gray_nearest(&alpha, grid_w, grid_h)?;
        let alpha = resize_gray_nearest(&alpha, resolution, resolution)?;

        let mut output = RgbaImage::new(resolution, resolution);
        for (x, y, pixel) in output.enumerate_pixels_mut() {
            let c = rgb.get_pixel(x, y);
            *pixel = image::Rgba([c[0], c[1], c[2], alpha.get_pixel(x, y)[0]]);
        }
        let postprocess = postprocess_start.elapsed();
        let total = total_start.elapsed();

        Ok((
            DynamicImage::ImageRgba8(output),
            PixelizeTimings {
                preprocess,
                inference,
                postprocess,
                total,
            },
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
// Preprocessing helpers
// ---------------------------------------------------------------------------

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
///
/// Upstream uses `astype(np.uint8)` without an explicit clamp, so out-of-range
/// values wrap.  We clamp instead (safer for ONNX Runtime numerics which may
/// differ by a tiny epsilon at the boundaries).
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

// ---------------------------------------------------------------------------
// Resize helpers
// ---------------------------------------------------------------------------

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

fn resize_rgb_nearest(input: &RgbImage, w: u32, h: u32) -> Result<RgbImage> {
    if input.width() == w && input.height() == h {
        return Ok(input.clone());
    }
    let src = fr::images::Image::from_vec_u8(
        input.width(),
        input.height(),
        input.as_raw().to_vec(),
        fr::PixelType::U8x3,
    )
    .context("nearest RGB resize src")?;
    let mut dst = fr::images::Image::new(w, h, fr::PixelType::U8x3);
    fr::Resizer::new()
        .resize(
            &src,
            &mut dst,
            Some(&fr::ResizeOptions::new().resize_alg(fr::ResizeAlg::Nearest)),
        )
        .context("nearest RGB resize")?;
    RgbImage::from_raw(w, h, dst.into_vec()).context("nearest RGB resize output")
}

fn extract_alpha(input: &RgbaImage) -> image::GrayImage {
    image::GrayImage::from_fn(input.width(), input.height(), |x, y| {
        image::Luma([input.get_pixel(x, y)[3]])
    })
}

fn resize_gray_nearest(input: &image::GrayImage, w: u32, h: u32) -> Result<image::GrayImage> {
    if input.width() == w && input.height() == h {
        return Ok(input.clone());
    }
    let src = fr::images::Image::from_vec_u8(
        input.width(),
        input.height(),
        input.as_raw().to_vec(),
        fr::PixelType::U8,
    )
    .context("nearest gray resize src")?;
    let mut dst = fr::images::Image::new(w, h, fr::PixelType::U8);
    fr::Resizer::new()
        .resize(
            &src,
            &mut dst,
            Some(&fr::ResizeOptions::new().resize_alg(fr::ResizeAlg::Nearest)),
        )
        .context("nearest gray resize")?;
    image::GrayImage::from_raw(w, h, dst.into_vec()).context("nearest gray resize output")
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn nchw_normalization_layout_and_values() {
        // R=0 → -1.0, G=127, B=255 → 1.0, A=42 ignored
        let img = RgbaImage::from_raw(1, 1, vec![0u8, 127, 255, 42]).unwrap();
        let data = rgba_to_normalized_nchw(&img);
        assert_eq!(data.shape(), &[1, 3, 1, 1]);
        // R channel
        assert!(
            (data[[0, 0, 0, 0]] - (-1.0_f32)).abs() < 1e-6,
            "R=-1 expected"
        );
        // G channel: 127/127.5 - 1 = 0.9961... - 1 = -0.0039...
        let expected_g = 127.0_f32 / 127.5 - 1.0;
        assert!((data[[0, 1, 0, 0]] - expected_g).abs() < 1e-5, "G mismatch");
        // B channel
        assert!((data[[0, 2, 0, 0]] - 1.0_f32).abs() < 1e-5, "B=1 expected");
    }

    #[test]
    fn nchw_layout_is_channel_first() {
        // 2×2 image with distinct R/G/B planes
        let mut img = RgbaImage::new(2, 2);
        img.put_pixel(0, 0, image::Rgba([10, 20, 30, 255]));
        img.put_pixel(1, 0, image::Rgba([40, 50, 60, 255]));
        img.put_pixel(0, 1, image::Rgba([70, 80, 90, 255]));
        img.put_pixel(1, 1, image::Rgba([100, 110, 120, 255]));
        let data = rgba_to_normalized_nchw(&img);
        assert_eq!(data.shape(), &[1, 3, 2, 2]);
        // Verify R plane is contiguous at offset 0
        assert!((data[[0, 0, 0, 0]] - (10.0_f32 / 127.5 - 1.0)).abs() < 1e-5);
        assert!((data[[0, 0, 0, 1]] - (40.0_f32 / 127.5 - 1.0)).abs() < 1e-5);
        assert!((data[[0, 1, 0, 0]] - (20.0_f32 / 127.5 - 1.0)).abs() < 1e-5);
        assert!((data[[0, 2, 0, 0]] - (30.0_f32 / 127.5 - 1.0)).abs() < 1e-5);
    }

    #[test]
    fn tensor_to_rgb_roundtrip() {
        // Forward-backward: nchw → tensor_to_rgb should recover original pixels
        let mut img = RgbaImage::new(2, 2);
        img.put_pixel(0, 0, image::Rgba([0, 128, 255, 255]));
        img.put_pixel(1, 0, image::Rgba([64, 192, 32, 255]));
        img.put_pixel(0, 1, image::Rgba([255, 0, 128, 255]));
        img.put_pixel(1, 1, image::Rgba([100, 100, 100, 255]));
        let nchw = rgba_to_normalized_nchw(&img);
        let dyn_arr = nchw.into_dyn();
        let recovered = tensor_to_rgb(dyn_arr).unwrap();
        // Due to f32 rounding the result may differ by ±1 from the original.
        for (orig, rec) in img.pixels().zip(recovered.pixels()) {
            for c in 0..3 {
                let diff = (i32::from(orig[c]) - i32::from(rec[c])).unsigned_abs();
                assert!(diff <= 1, "channel {c}: orig={} rec={}", orig[c], rec[c]);
            }
        }
    }

    #[test]
    fn process_geometry_cell_size_4() {
        // Without a real model we can only check the geometry path doesn't panic
        // and that preprocess::rescale_into_bounds is idempotent for a normal image.
        let img = RgbaImage::from_pixel(256, 256, image::Rgba([128, 64, 32, 255]));
        let result = preprocess::rescale_into_bounds(img).unwrap();
        assert_eq!(result.dimensions(), (256, 256));
    }

    #[test]
    fn rescale_shrinks_oversized() {
        let big = RgbaImage::from_pixel(8192, 4096, image::Rgba([0, 0, 0, 255]));
        let result = preprocess::rescale_into_bounds(big).unwrap();
        assert!(result.width() <= 4000 && result.height() <= 4000);
    }

    #[test]
    fn rescale_grows_undersized() {
        let small = RgbaImage::from_pixel(64, 64, image::Rgba([0, 0, 0, 255]));
        let result = preprocess::rescale_into_bounds(small).unwrap();
        assert!(result.width() >= 128 && result.height() >= 128);
    }
}
