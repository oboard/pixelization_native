use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use clap::Parser;
use pixelization::{Pixelizer, SimpleCleanupOptions};
use walkdir::WalkDir;

/// High-quality true-bitmap Pixel Art pipeline.
///
/// Runs WuZongWei6 ONNX teacher at long_edge*teacher_scale and applies a small
/// Rust simple cleanup pass to collapse known 4px cells into true bitmap pixels.
#[derive(Debug, Parser)]
#[command(name = "hq-pixelize", version)]
struct Args {
    /// Input PNG/JPEG/WebP file, or a directory for batch processing.
    input: PathBuf,
    /// Output file (single input with one long edge) or directory.
    output: PathBuf,
    /// Path to the exported dynamic-shape ONNX teacher model.
    #[arg(long, default_value = "models/pixelization.onnx")]
    model: PathBuf,
    /// Target final bitmap long edge(s), e.g. 128 56 32.
    #[arg(long, value_delimiter = ',', default_value = "128")]
    long_edges: Vec<u32>,
    /// Teacher high-res multiplier. 4 matches Wu teacher's trained cell lattice.
    #[arg(long, default_value_t = 4)]
    teacher_scale: u32,
    /// ONNX Runtime intra-op thread count. 0 = runtime default.
    #[arg(long, default_value_t = 4)]
    threads: usize,
    /// Palette merge threshold in RGB distance. Higher merges more shades.
    #[arg(long, default_value_t = 18.0)]
    merge_threshold: f32,
    /// Optional max palette colors.
    #[arg(long)]
    max_colors: Option<usize>,
    /// Neighborhood smoothing passes.
    #[arg(long, default_value_t = 2)]
    smooth_passes: usize,
}

fn main() -> Result<()> {
    let args = Args::parse();
    if args.long_edges.is_empty() {
        bail!("--long-edges must not be empty");
    }
    let pixelizer = Pixelizer::load_with_threads(&args.model, args.threads)
        .with_context(|| format!("load model '{}'", args.model.display()))?;

    let cleanup = SimpleCleanupOptions {
        pitch: 4,
        merge_threshold: args.merge_threshold,
        max_colors: args.max_colors,
        smooth_passes: args.smooth_passes,
    };

    if args.input.is_file() {
        if args.long_edges.len() == 1 && !args.output.is_dir() {
            process_one(&pixelizer, &args.input, &args.output, args.long_edges[0], args.teacher_scale, cleanup)?;
        } else {
            std::fs::create_dir_all(&args.output)
                .with_context(|| format!("create output dir '{}'", args.output.display()))?;
            for &edge in &args.long_edges {
                let stem = args.input.file_stem().and_then(|s| s.to_str()).unwrap_or("image");
                let out = args.output.join(edge.to_string()).join(format!("{stem}_{edge}.png"));
                if let Some(parent) = out.parent() {
                    std::fs::create_dir_all(parent)?;
                }
                process_one(&pixelizer, &args.input, &out, edge, args.teacher_scale, cleanup)?;
            }
        }
    } else if args.input.is_dir() {
        std::fs::create_dir_all(&args.output)
            .with_context(|| format!("create output dir '{}'", args.output.display()))?;
        for entry in WalkDir::new(&args.input)
            .into_iter()
            .filter_map(|e| e.ok())
            .filter(|e| e.file_type().is_file())
            .filter(|e| is_supported(e.path()))
        {
            let stem = entry.path().file_stem().and_then(|s| s.to_str()).unwrap_or("image");
            for &edge in &args.long_edges {
                let out = args.output.join(edge.to_string()).join(format!("{stem}_{edge}.png"));
                if let Some(parent) = out.parent() {
                    std::fs::create_dir_all(parent)?;
                }
                process_one(&pixelizer, entry.path(), &out, edge, args.teacher_scale, cleanup)?;
            }
        }
    } else {
        bail!("input does not exist: {}", args.input.display());
    }
    Ok(())
}

fn process_one(
    px: &Pixelizer,
    input: &Path,
    output: &Path,
    long_edge: u32,
    teacher_scale: u32,
    cleanup: SimpleCleanupOptions,
) -> Result<()> {
    let img = image::open(input).with_context(|| format!("open '{}'", input.display()))?;
    let (result, timings, report) = px
        .process_high_quality_bitmap_timed(&img, long_edge, teacher_scale, cleanup)
        .with_context(|| format!("high-quality pixelize '{}'", input.display()))?;
    result
        .save(output)
        .with_context(|| format!("save '{}'", output.display()))?;
    eprintln!(
        "{} → {} [{}x{}, palette={}, pre={:.2}ms infer={:.2}ms clean={:.2}ms total={:.2}ms]",
        input.display(),
        output.display(),
        report.cells_w,
        report.cells_h,
        report.palette_size,
        timings.preprocess.as_secs_f64() * 1000.0,
        timings.inference.as_secs_f64() * 1000.0,
        timings.postprocess.as_secs_f64() * 1000.0,
        timings.total.as_secs_f64() * 1000.0,
    );
    Ok(())
}

fn is_supported(path: &Path) -> bool {
    path.extension()
        .and_then(|e| e.to_str())
        .map(|e| matches!(e.to_ascii_lowercase().as_str(), "png" | "jpg" | "jpeg" | "webp"))
        .unwrap_or(false)
}
