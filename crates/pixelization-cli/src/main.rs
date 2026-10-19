use std::path::{Path, PathBuf};

use anyhow::{Context, Result, bail};
use clap::Parser;
use pixelization::{PixelizeOptions, Pixelizer};
use walkdir::WalkDir;

/// WuZongWei6/Pixelization 的跨平台 CPU 命令行实现。
#[derive(Debug, Parser)]
#[command(name = "pixelize", version)]
struct Args {
    /// 输入 PNG、JPEG、WebP 图片或目录。
    input: PathBuf,
    /// 单图输出文件，或批处理输出目录。
    output: PathBuf,
    /// 由生成器和 AliasNet 导出的 ONNX 模型。
    #[arg(long, default_value = "models/pixelization.onnx")]
    model: PathBuf,
    /// 最终像素块边长，与上游 `test_pro.py --cell_size` 一致。
    #[arg(long, default_value_t = 4, value_parser = clap::value_parser!(u32).range(1..))]
    cell_size: u32,
    /// ONNX Runtime CPU 线程数；0 表示运行时默认值。
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
            bail!("output must be a directory when input is a directory");
        }
        std::fs::create_dir_all(&args.output)
            .with_context(|| format!("create output directory '{}'", args.output.display()))?;
        for entry in WalkDir::new(&args.input)
            .into_iter()
            .filter_map(Result::ok)
            .filter(|entry| entry.file_type().is_file())
            .filter(|entry| is_supported(entry.path()))
        {
            let relative = entry
                .path()
                .strip_prefix(&args.input)
                .context("strip input directory prefix")?;
            let output = args.output.join(relative);
            if let Some(parent) = output.parent() {
                std::fs::create_dir_all(parent)?;
            }
            process_one(&pixelizer, entry.path(), &output, args.cell_size)?;
        }
    } else {
        bail!("input does not exist: {}", args.input.display());
    }

    Ok(())
}

fn process_one(pixelizer: &Pixelizer, input: &Path, output: &Path, cell_size: u32) -> Result<()> {
    let image = image::open(input).with_context(|| format!("open '{}'", input.display()))?;
    let result = pixelizer
        .process(&image, PixelizeOptions { cell_size })
        .with_context(|| format!("pixelize '{}'", input.display()))?;
    result
        .save(output)
        .with_context(|| format!("save '{}'", output.display()))?;
    eprintln!("{} → {}", input.display(), output.display());
    Ok(())
}

fn is_supported(path: &Path) -> bool {
    path.extension()
        .and_then(|extension| extension.to_str())
        .is_some_and(|extension| {
            matches!(
                extension.to_ascii_lowercase().as_str(),
                "png" | "jpg" | "jpeg" | "webp"
            )
        })
}
