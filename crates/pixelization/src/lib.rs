//! `WuZongWei6/Pixelization` 的跨平台 CPU 推理实现。
//!
//! ONNX 模型包含上游 Test Pro 的生成器与 AliasNet；Rust 侧复刻图像尺寸、
//! 归一化和像素网格缩放，并将结果无损收缩到最小最近邻逻辑网格。

mod error;
pub mod normalize;
pub mod preprocess;

pub use error::PixelizationError;

use std::{path::Path, sync::Mutex};

use anyhow::{Context, Result};
use fast_image_resize as fr;
use image::{DynamicImage, Rgb, RgbImage};
use ndarray::Array4;
use ort::{
    session::{Session, SessionInputValue},
    value::{TensorRef, ValueType},
};

const MODEL_CELL_SIZE: u32 = 4;

/// 控制最终像素块大小。
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PixelizeOptions {
    pub cell_size: u32,
}

impl Default for PixelizeOptions {
    fn default() -> Self {
        Self { cell_size: 4 }
    }
}

/// 基于 ONNX Runtime CPU 后端的像素化引擎。
pub struct Pixelizer {
    session: Mutex<Session>,
    input_name: String,
}

impl Pixelizer {
    pub fn load(path: impl AsRef<Path>) -> Result<Self> {
        Self::load_with_threads(path, 0)
    }

    pub fn load_with_threads(path: impl AsRef<Path>, threads: usize) -> Result<Self> {
        let path = path.as_ref();
        let session = Session::builder()
            .map_err(|error| anyhow::anyhow!("create ONNX Runtime session: {error}"))?
            .with_intra_threads(threads)
            .map_err(|error| anyhow::anyhow!("set ONNX Runtime threads: {error}"))?
            .with_inter_threads(1)
            .map_err(|error| anyhow::anyhow!("set ONNX Runtime inter-op threads: {error}"))?
            .commit_from_file(path)
            .map_err(|error| anyhow::anyhow!("load ONNX model '{}': {error}", path.display()))?;

        if session.inputs().len() != 1 {
            return Err(PixelizationError::InvalidInputCount(session.inputs().len()).into());
        }
        let input = &session.inputs()[0];
        let ValueType::Tensor { shape, .. } = input.dtype() else {
            return Err(PixelizationError::InvalidModelInput(Vec::new()).into());
        };
        let dimensions = shape.to_vec();
        if dimensions.len() != 4 {
            return Err(PixelizationError::InvalidModelInput(dimensions).into());
        }
        if dimensions[1] != 3 {
            return Err(PixelizationError::UnsupportedInputShape(dimensions).into());
        }

        Ok(Self {
            input_name: input.name().to_owned(),
            session: Mutex::new(session),
        })
    }

    /// 按上游 `test_pro.py` 的几何流程处理一张图片。
    pub fn process(&self, image: &DynamicImage, options: PixelizeOptions) -> Result<DynamicImage> {
        if options.cell_size == 0 {
            return Err(PixelizationError::InvalidCellSize.into());
        }

        let source = preprocess::rescale_into_bounds(image.to_rgb8())?;
        let target_width = source.width() / options.cell_size * MODEL_CELL_SIZE;
        let target_height = source.height() / options.cell_size * MODEL_CELL_SIZE;
        if target_width == 0 || target_height == 0 {
            return Err(PixelizationError::EmptyGrid.into());
        }

        let model_input = resize_rgb_bicubic(&source, target_width, target_height)?;
        let tensor = rgb_to_normalized_nchw(&model_input);
        let generated = tensor_to_rgb(self.infer(tensor)?)?;

        let grid_width = generated.width() / MODEL_CELL_SIZE;
        let grid_height = generated.height() / MODEL_CELL_SIZE;
        if grid_width == 0 || grid_height == 0 {
            return Err(PixelizationError::EmptyGrid.into());
        }
        let grid = resize_rgb_nearest(&generated, grid_width, grid_height)?;
        let output = resize_rgb_nearest(
            &grid,
            grid_width * options.cell_size,
            grid_height * options.cell_size,
        )?;
        let normalized = normalize::smallest_lossless_grid(&output);

        Ok(DynamicImage::ImageRgb8(normalized))
    }

    fn infer(&self, input: Array4<f32>) -> Result<ndarray::ArrayD<f32>> {
        let tensor = TensorRef::from_array_view(&input)
            .map_err(|error| anyhow::anyhow!("create model input tensor: {error}"))?;
        let mut session = self
            .session
            .lock()
            .map_err(|_| anyhow::anyhow!("ONNX Runtime session lock poisoned"))?;
        let outputs = session
            .run(ort::inputs![self.input_name.as_str() => SessionInputValue::from(tensor)])
            .map_err(|error| anyhow::anyhow!("run ONNX inference: {error}"))?;
        if outputs.len() == 0 {
            return Err(PixelizationError::MissingModelOutput.into());
        }
        let (shape, values) = outputs[0]
            .try_extract_tensor::<f32>()
            .map_err(|error| anyhow::anyhow!("extract model output tensor: {error}"))?;
        ndarray::ArrayD::from_shape_vec(shape.to_ixdyn(), values.to_vec())
            .context("copy model output tensor")
    }
}

fn rgb_to_normalized_nchw(image: &RgbImage) -> Array4<f32> {
    let (width, height) = image.dimensions();
    let plane = (width * height) as usize;
    let mut values = vec![0.0; plane * 3];
    for (index, pixel) in image.pixels().enumerate() {
        values[index] = f32::from(pixel[0]) / 127.5 - 1.0;
        values[plane + index] = f32::from(pixel[1]) / 127.5 - 1.0;
        values[plane * 2 + index] = f32::from(pixel[2]) / 127.5 - 1.0;
    }
    Array4::from_shape_vec((1, 3, height as usize, width as usize), values)
        .expect("image dimensions determine tensor size")
}

fn tensor_to_rgb(tensor: ndarray::ArrayD<f32>) -> Result<RgbImage> {
    let shape = tensor.shape();
    if shape.len() != 4 || shape[0] != 1 || shape[1] != 3 {
        return Err(PixelizationError::InvalidModelOutput(shape.to_vec()).into());
    }

    let (height, width) = (shape[2] as u32, shape[3] as u32);
    let plane = (width * height) as usize;
    let values = tensor
        .as_slice()
        .context("model output is not contiguous")?;
    let mut image = RgbImage::new(width, height);
    for (index, pixel) in image.pixels_mut().enumerate() {
        let channel = |value: f32| ((value + 1.0) * 127.5).clamp(0.0, 255.0) as u8;
        *pixel = Rgb([
            channel(values[index]),
            channel(values[plane + index]),
            channel(values[plane * 2 + index]),
        ]);
    }
    Ok(image)
}

fn resize_rgb_bicubic(input: &RgbImage, width: u32, height: u32) -> Result<RgbImage> {
    resize_rgb(
        input,
        width,
        height,
        fr::ResizeAlg::Convolution(fr::FilterType::CatmullRom),
    )
}

fn resize_rgb_nearest(input: &RgbImage, width: u32, height: u32) -> Result<RgbImage> {
    resize_rgb(input, width, height, fr::ResizeAlg::Nearest)
}

fn resize_rgb(
    input: &RgbImage,
    width: u32,
    height: u32,
    algorithm: fr::ResizeAlg,
) -> Result<RgbImage> {
    if input.dimensions() == (width, height) {
        return Ok(input.clone());
    }
    let source = fr::images::Image::from_vec_u8(
        input.width(),
        input.height(),
        input.as_raw().to_vec(),
        fr::PixelType::U8x3,
    )
    .context("create resize source")?;
    let mut destination = fr::images::Image::new(width, height, fr::PixelType::U8x3);
    fr::Resizer::new()
        .resize(
            &source,
            &mut destination,
            Some(&fr::ResizeOptions::new().resize_alg(algorithm)),
        )
        .context("resize image")?;
    RgbImage::from_raw(width, height, destination.into_vec()).context("create resized image")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalization_uses_channel_first_layout() {
        let image = RgbImage::from_raw(2, 1, vec![0, 127, 255, 255, 64, 32]).unwrap();
        let tensor = rgb_to_normalized_nchw(&image);
        assert_eq!(tensor.shape(), &[1, 3, 1, 2]);
        assert_eq!(tensor[[0, 0, 0, 0]], -1.0);
        assert_eq!(tensor[[0, 0, 0, 1]], 1.0);
        assert_eq!(tensor[[0, 2, 0, 0]], 1.0);
    }

    #[test]
    fn tensor_conversion_preserves_rgb_values() {
        let image = RgbImage::from_raw(2, 1, vec![0, 128, 255, 64, 192, 32]).unwrap();
        let output = tensor_to_rgb(rgb_to_normalized_nchw(&image).into_dyn()).unwrap();
        for (expected, actual) in image.pixels().zip(output.pixels()) {
            for channel in 0..3 {
                assert!((i16::from(expected[channel]) - i16::from(actual[channel])).abs() <= 1);
            }
        }
    }
}
