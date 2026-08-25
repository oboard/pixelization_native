use std::{path::{Path, PathBuf}, time::Duration};

use anyhow::{bail, Context, Result};
use clap::Parser;
use image::DynamicImage;
use pixelization::Pixelizer;

#[derive(Debug, Parser)]
#[command(name = "lowres-bench", version, about = "Benchmark fixed low-resolution Pixelization inference")]
struct Args {
    /// Input PNG/JPEG/WebP image, or a directory whose first supported image is used.
    input: PathBuf,

    /// Path to the ONNX model.
    #[arg(long, default_value = "models/pixelization.onnx")]
    model: PathBuf,

    /// ONNX Runtime intra-op thread count. 0 = runtime default.
    #[arg(long, default_value_t = 4)]
    threads: usize,

    /// Number of measured warm inference iterations per resolution.
    #[arg(long, default_value_t = 50)]
    iterations: usize,

    /// Comma-separated square model input resolutions. Each must be divisible by 4.
    #[arg(long, value_delimiter = ',', default_value = "512,256,128,96,64,56,48,32")]
    resolutions: Vec<u32>,

    /// Directory for visual low-resolution outputs.
    #[arg(long, default_value = "outputs/lowres")]
    output_dir: PathBuf,

    /// Comma-separated resolutions to save as visual outputs.
    #[arg(long, value_delimiter = ',', default_value = "128,56,32")]
    save_resolutions: Vec<u32>,
}

#[derive(Debug)]
struct Stats {
    p50: f64,
    p95: f64,
}

#[derive(Debug)]
struct Row {
    resolution: u32,
    preprocess: Stats,
    inference: Stats,
    postprocess: Stats,
    total: Stats,
    speedup: f64,
    peak_rss_mb: f64,
}

fn main() -> Result<()> {
    let args = Args::parse();
    if args.iterations == 0 {
        bail!("--iterations must be >= 1");
    }
    for &r in &args.resolutions {
        if r == 0 || r % 4 != 0 {
            bail!("resolution must be divisible by 4, got {r}");
        }
    }

    let input_path = resolve_input(&args.input)?;
    let image = image::open(&input_path).with_context(|| format!("open '{}'", input_path.display()))?;
    let pixelizer = Pixelizer::load_with_threads(&args.model, args.threads)
        .with_context(|| format!("load model '{}'", args.model.display()))?;

    std::fs::create_dir_all(&args.output_dir)
        .with_context(|| format!("create output dir '{}'", args.output_dir.display()))?;

    let mut rows = Vec::new();
    let mut baseline_total = None;

    for &resolution in &args.resolutions {
        // One unmeasured warmup pass to populate runtime caches.
        let _ = pixelizer.process_lowres_square_timed(&image, resolution)?;

        let mut preprocess = Vec::with_capacity(args.iterations);
        let mut inference = Vec::with_capacity(args.iterations);
        let mut postprocess = Vec::with_capacity(args.iterations);
        let mut total = Vec::with_capacity(args.iterations);

        let mut saved = false;
        for _ in 0..args.iterations {
            let (out, timings) = pixelizer.process_lowres_square_timed(&image, resolution)?;
            preprocess.push(ms(timings.preprocess));
            inference.push(ms(timings.inference));
            postprocess.push(ms(timings.postprocess));
            total.push(ms(timings.total));

            if !saved && args.save_resolutions.contains(&resolution) {
                save_visual(&args.output_dir, resolution, &input_path, &out)?;
                saved = true;
            }
        }

        let total_stats = stats(total);
        let base = *baseline_total.get_or_insert(total_stats.p50);
        rows.push(Row {
            resolution,
            preprocess: stats(preprocess),
            inference: stats(inference),
            postprocess: stats(postprocess),
            speedup: base / total_stats.p50,
            total: total_stats,
            peak_rss_mb: peak_rss_mb(),
        });
    }

    print_report(&args, &input_path, &rows);
    Ok(())
}

fn resolve_input(path: &Path) -> Result<PathBuf> {
    if path.is_file() {
        return Ok(path.to_path_buf());
    }
    if !path.is_dir() {
        bail!("input does not exist: {}", path.display());
    }
    let mut files: Vec<_> = std::fs::read_dir(path)?
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| is_supported(p))
        .collect();
    files.sort();
    files.into_iter().next().with_context(|| format!("no supported images in '{}'", path.display()))
}

fn is_supported(path: &Path) -> bool {
    path.extension()
        .and_then(|e| e.to_str())
        .map(|e| matches!(e.to_ascii_lowercase().as_str(), "png" | "jpg" | "jpeg" | "webp"))
        .unwrap_or(false)
}

fn save_visual(dir: &Path, resolution: u32, input: &Path, image: &DynamicImage) -> Result<()> {
    let out_dir = dir.join(resolution.to_string());
    std::fs::create_dir_all(&out_dir)?;
    let stem = input.file_stem().and_then(|s| s.to_str()).unwrap_or("image");
    let out = out_dir.join(format!("{stem}_{resolution}.png"));
    image.save(&out).with_context(|| format!("save '{}'", out.display()))?;
    Ok(())
}

fn ms(d: Duration) -> f64 {
    d.as_secs_f64() * 1000.0
}

fn stats(mut values: Vec<f64>) -> Stats {
    values.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let n = values.len();
    let p50_idx = ((n as f64 - 1.0) * 0.50).round() as usize;
    let p95_idx = ((n as f64 - 1.0) * 0.95).round() as usize;
    Stats { p50: values[p50_idx], p95: values[p95_idx] }
}

fn print_report(args: &Args, input: &Path, rows: &[Row]) {
    println!("# Low-resolution inference benchmark");
    println!();
    println!("- input: `{}`", input.display());
    println!("- model: `{}`", args.model.display());
    println!("- threads: {}", args.threads);
    println!("- iterations per resolution: {}", args.iterations);
    println!("- backend: ONNX Runtime CPU, FP32");
    println!();
    println!("## Summary");
    println!();
    println!("| Resolution | Inference p50 | Total p50 | Speedup |");
    println!("|------------|---------------|-----------|---------|");
    for r in rows {
        println!("| {} | {:.2} ms | {:.2} ms | {:.2}× |", r.resolution, r.inference.p50, r.total.p50, r.speedup);
    }
    println!();
    println!("## Detailed timings");
    println!();
    println!("| Resolution | Preprocess p50/p95 | Inference p50/p95 | Postprocess p50/p95 | Total p50/p95 | Peak RSS |");
    println!("|------------|--------------------|-------------------|---------------------|---------------|----------|");
    for r in rows {
        println!(
            "| {} | {:.2}/{:.2} ms | {:.2}/{:.2} ms | {:.2}/{:.2} ms | {:.2}/{:.2} ms | {:.1} MB |",
            r.resolution,
            r.preprocess.p50,
            r.preprocess.p95,
            r.inference.p50,
            r.inference.p95,
            r.postprocess.p50,
            r.postprocess.p95,
            r.total.p50,
            r.total.p95,
            r.peak_rss_mb,
        );
    }
}

#[cfg(target_os = "macos")]
fn peak_rss_mb() -> f64 {
    unsafe {
        let mut usage: libc::rusage = std::mem::zeroed();
        if libc::getrusage(libc::RUSAGE_SELF, &mut usage) == 0 {
            usage.ru_maxrss as f64 / 1024.0 / 1024.0
        } else {
            f64::NAN
        }
    }
}

#[cfg(target_os = "linux")]
fn peak_rss_mb() -> f64 {
    unsafe {
        let mut usage: libc::rusage = std::mem::zeroed();
        if libc::getrusage(libc::RUSAGE_SELF, &mut usage) == 0 {
            // Linux ru_maxrss is KiB.
            usage.ru_maxrss as f64 / 1024.0
        } else {
            f64::NAN
        }
    }
}

#[cfg(not(any(target_os = "macos", target_os = "linux")))]
fn peak_rss_mb() -> f64 {
    f64::NAN
}
