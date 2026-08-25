use std::path::{Path, PathBuf};

use anyhow::{Context, Result, bail};
use clap::Parser;
use pixelization::{PixelizeOptions, Pixelizer};
use walkdir::WalkDir;

/// CPU-only Pixel Art engine  —  ONNX Runtime / CPU backend.
///
/// Examples:
///   pixelize input.png output.png --cell-size 4
///   pixelize input.png output.png --model models/pixelization.onnx --threads 8
///   pixelize ./input ./output --cell-size 4
#[derive(Debug, Parser)]
#[command(name = "pixelize", version)]
struct Args {
    /// Input PNG/JPEG/WebP file, or a directory for batch processing.
    input: PathBuf,
    /// Output file (single input) or directory (directory input).
    output: PathBuf,
    /// Path to the exported static-shape ONNX model.
    #[arg(long, default_value = "models/pixelization.onnx")]
    model: PathBuf,
    /// Pixel cell size (nearest-neighbor upscale factor for the output grid).
    /// The network always infers at the trained 4-px lattice.
    #[arg(long, default_value_t = 4, value_parser = clap::value_parser!(u32).range(1..))]
    cell_size: u32,
    /// ONNX Runtime intra-op thread count. 0 = runtime default (all cores).
    #[arg(long, default_value_t = 0)]
    threads: usize,
}

fn main() -> Result<()> {
    let args = Args::parse();
    let pixelizer = Pixelizer::load_with_threads(&args.model, args.threads)
        .with_context(|| format!("load model '{}'", args.model.display()))?;

    if args.input.is_file() {
        process_one(&pixelizer, &args.input, &args.output, args.cell_size)?;
    } else if args.input.is_dir() {
        if args.output.exists() && !args.output.is_dir() {
            bail!("--output must be a directory when --input is a directory");
        }
        std::fs::create_dir_all(&args.output)
            .with_context(|| format!("create output dir '{}'", args.output.display()))?;
        for entry in WalkDir::new(&args.input)
            .into_iter()
            .filter_map(|e| e.ok())
            .filter(|e| e.file_type().is_file())
            .filter(|e| is_supported(e.path()))
        {
            let rel = entry
                .path()
                .strip_prefix(&args.input)
                .context("strip input prefix")?;
            let out = args.output.join(rel);
            if let Some(parent) = out.parent() {
                std::fs::create_dir_all(parent)?;
            }
            process_one(&pixelizer, entry.path(), &out, args.cell_size)?;
        }
    } else {
        bail!("input does not exist: {}", args.input.display());
    }
    Ok(())
}

fn process_one(px: &Pixelizer, input: &Path, output: &Path, cell_size: u32) -> Result<()> {
    let img = image::open(input).with_context(|| format!("open '{}'", input.display()))?;
    let result = px
        .process(&img, PixelizeOptions { cell_size })
        .with_context(|| format!("pixelize '{}'", input.display()))?;
    result
        .save(output)
        .with_context(|| format!("save '{}'", output.display()))?;
    eprintln!("{} → {}", input.display(), output.display());
    Ok(())
}

fn is_supported(path: &Path) -> bool {
    path.extension()
        .and_then(|e| e.to_str())
        .map(|e| {
            matches!(
                e.to_ascii_lowercase().as_str(),
                "png" | "jpg" | "jpeg" | "webp"
            )
        })
        .unwrap_or(false)
}
