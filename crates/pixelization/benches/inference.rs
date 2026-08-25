//! Criterion benchmarks for pixelization inference.
//!
//! Set PIXELIZATION_MODEL before running:
//!
//!   PIXELIZATION_MODEL=models/pixelization.onnx \
//!     cargo bench -p pixelization --bench inference
//!
//! Reports: cold-start load, warm inference thread-sweep (1/2/4/8/16), cell-size sweep.

use criterion::{BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use image::{DynamicImage, RgbaImage};
use pixelization::{PixelizeOptions, Pixelizer};

const MODEL_ENV: &str = "PIXELIZATION_MODEL";
const THREAD_COUNTS: [usize; 5] = [1, 2, 4, 8, 16];

fn model_path() -> Option<String> {
    let path = std::env::var(MODEL_ENV).ok()?;
    if std::path::Path::new(&path).exists() {
        Some(path)
    } else {
        eprintln!("[bench] model not found at '{path}'; set {MODEL_ENV}=<path> to enable");
        None
    }
}

fn test_image(w: u32, h: u32) -> DynamicImage {
    DynamicImage::ImageRgba8(RgbaImage::from_pixel(
        w,
        h,
        image::Rgba([127u8, 80, 40, 255]),
    ))
}

/// Warm inference — thread sweep 1/2/4/8/16 at 512×512 cell_size=4.
fn bench_warm_inference(c: &mut Criterion) {
    let Some(model) = model_path() else { return };
    let image = test_image(512, 512);
    let options = PixelizeOptions { cell_size: 4 };
    let mut group = c.benchmark_group("warm_inference_thread_sweep");
    group.throughput(Throughput::Elements(1));
    group.sample_size(10); // Reduce sample size for long-running benchmarks
    for &threads in &THREAD_COUNTS {
        let px = Pixelizer::load_with_threads(&model, threads).expect("load");
        group.bench_with_input(
            BenchmarkId::new("512x512_cell4", format!("t{threads}")),
            &threads,
            |b, _| b.iter(|| px.process(&image, options).expect("infer")),
        );
    }
    group.finish();
}

/// Cold model load (includes ORT session construction).
fn bench_cold_start(c: &mut Criterion) {
    let Some(model) = model_path() else { return };
    let mut group = c.benchmark_group("cold_start");
    group.sample_size(10);
    group.bench_function("load_model", |b| {
        b.iter(|| Pixelizer::load(&model).expect("cold load"))
    });
    group.finish();
}

/// cell_size sweep 2/4/6/8 at 512×512, default threads.
fn bench_cell_sizes(c: &mut Criterion) {
    let Some(model) = model_path() else { return };
    let px = Pixelizer::load(&model).expect("load");
    let image = test_image(512, 512);
    let mut group = c.benchmark_group("cell_size_sweep_512x512");
    group.throughput(Throughput::Elements(1));
    group.sample_size(10);
    for &cell_size in &[2u32, 4, 6, 8] {
        let opts = PixelizeOptions { cell_size };
        group.bench_with_input(
            BenchmarkId::from_parameter(format!("cell{cell_size}")),
            &cell_size,
            |b, _| b.iter(|| px.process(&image, opts).expect("infer")),
        );
    }
    group.finish();
}

criterion_group!(
    benches,
    bench_warm_inference,
    bench_cold_start,
    bench_cell_sizes
);
criterion_main!(benches);
