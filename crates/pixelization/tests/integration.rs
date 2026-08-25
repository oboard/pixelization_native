//! Integration tests — each test is gated on the ONNX model being present.
//! Run with:
//!   PIXELIZATION_MODEL=models/pixelization.onnx cargo test --test integration

use std::path::PathBuf;

use image::{DynamicImage, GenericImageView, RgbaImage};
use pixelization::{PixelizeOptions, Pixelizer};

fn model_path() -> Option<PathBuf> {
    let path = PathBuf::from(
        std::env::var("PIXELIZATION_MODEL").unwrap_or_else(|_| "models/pixelization.onnx".into()),
    );
    if path.exists() { Some(path) } else { None }
}

fn load_or_skip() -> Option<Pixelizer> {
    let path = model_path()?;
    Some(Pixelizer::load(&path).expect("load model"))
}

#[test]
fn load_model_and_check_input_size() {
    let Some(px) = load_or_skip() else {
        println!("SKIP: no model at PIXELIZATION_MODEL");
        return;
    };
    let (w, h) = px.input_size();
    // Dynamic-shape model returns (0, 0)
    // Static-shape model returns the actual size
    println!("Model input size: {}x{}", w, h);
}

#[test]
fn process_rgb_opaque_cell_size_4() {
    let Some(px) = load_or_skip() else { return };
    let img = DynamicImage::ImageRgba8(RgbaImage::from_pixel(
        512,
        512,
        image::Rgba([128, 80, 40, 255]),
    ));
    let result = px
        .process(&img, PixelizeOptions { cell_size: 4 })
        .expect("process");
    let (rw, rh) = result.dimensions();
    // Input 512×512, cell_size=4, best_cell=4 → grid 128×128 → output 128*4=512×512
    assert_eq!((rw, rh), (512, 512), "output dims mismatch at cell_size=4");
}

#[test]
fn process_cell_size_2() {
    let Some(px) = load_or_skip() else { return };
    let img = DynamicImage::ImageRgba8(RgbaImage::from_pixel(
        512,
        512,
        image::Rgba([200, 100, 50, 255]),
    ));
    let result = px
        .process(&img, PixelizeOptions { cell_size: 2 })
        .expect("process");
    let (rw, rh) = result.dimensions();
    // cell_size=2: target_w=(512//2)*4=1024, center-crop 1024 (÷4 ok), model→512,
    // then grid=1024/4=256, out=256*2=512
    assert_eq!((rw, rh), (512, 512));
}

#[test]
fn process_cell_size_8() {
    let Some(px) = load_or_skip() else { return };
    let img = DynamicImage::ImageRgba8(RgbaImage::from_pixel(
        512,
        512,
        image::Rgba([10, 20, 30, 255]),
    ));
    let result = px
        .process(&img, PixelizeOptions { cell_size: 8 })
        .expect("process");
    let (rw, rh) = result.dimensions();
    // cell_size=8: target_w=(512//8)*4=256, grid=256/4=64, out=64*8=512
    assert_eq!((rw, rh), (512, 512));
}

#[test]
fn process_preserves_alpha_passthrough() {
    let Some(px) = load_or_skip() else { return };
    // Image that is fully transparent — alpha should pass through grid geometry.
    let img = DynamicImage::ImageRgba8(RgbaImage::from_pixel(512, 512, image::Rgba([0, 0, 0, 0])));
    let result = px
        .process(&img, PixelizeOptions { cell_size: 4 })
        .expect("process");
    let rgba = result.to_rgba8();
    // All output alpha should be 0 (nearest-neighbor of transparent input).
    assert!(
        rgba.pixels().all(|p| p[3] == 0),
        "transparent input should produce transparent output"
    );
}

#[test]
fn process_non_square_input() {
    let Some(px) = load_or_skip() else { return };
    let img = DynamicImage::ImageRgba8(RgbaImage::from_pixel(
        640,
        480,
        image::Rgba([100, 150, 200, 255]),
    ));
    let result = px
        .process(&img, PixelizeOptions { cell_size: 4 })
        .expect("non-square");
    let (rw, rh) = result.dimensions();
    assert!(rw > 0 && rh > 0);
}

#[test]
fn reject_cell_size_zero() {
    let Some(px) = load_or_skip() else { return };
    let img = DynamicImage::ImageRgba8(RgbaImage::from_pixel(64, 64, image::Rgba([0, 0, 0, 255])));
    let err = px.process(&img, PixelizeOptions { cell_size: 0 });
    assert!(err.is_err(), "cell_size=0 must be an error");
}

#[test]
fn load_missing_model_returns_error() {
    let result = Pixelizer::load("/nonexistent/model.onnx");
    assert!(result.is_err(), "loading a nonexistent model must fail");
}
