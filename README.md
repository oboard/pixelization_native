# Pixelization Native

High-performance, pure CPU, Rust native Pixel Art engine. Port of [WuZongWei6/Pixelization](https://github.com/WuZongWei6/Pixelization) with a Rust-native true-bitmap cleanup stage.

## Features

- **True bitmap output** — one PNG pixel is one logical pixel; no upscale, no ÷4→×4 blocks
- **Aspect-ratio preserving** — targets are long-edge values (e.g. 128/56/32)
- **Pure CPU inference** via ONNX Runtime (FP32)
- **Rust cleanup pipeline** — palette merge + smoothing + optional perfectPixel grid refinement, no Python/NumPy/OpenCV at runtime
- **Cross-platform** - macOS (ARM64/x86_64), Linux (ARM64/x86_64), Windows (x86_64)
- **Dynamic input size** - any image size divisible by 4

## Quick Start

### 1. Download Weights

```bash
# From Google Drive (see upstream repo for links)
# Place files at:
#   checkpoints/160_net_G_A.pth (144 MB)
#   alias_net.pth (34 MB)
```

### 2. Set Up Python Tooling with uv

Only needed to export the ONNX model; not needed at runtime.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
```

### 3. Export ONNX Model

```bash
uv run python export/export_onnx.py \
    --generator checkpoints/160_net_G_A.pth \
    --alias alias_net.pth \
    --output models/pixelization.onnx
```

### 4. Run

```bash
# Build
cargo build --release

# Single image, long edge 128 (default)
target/release/pixelize input.png output.png

# Multi-size true-bitmap outputs
target/release/pixelize input.png out_dir --long-edges 128,56,32

# Batch directory processing
target/release/pixelize ./input_dir ./output_dir --long-edges 128,56,32
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--model` | `models/pixelization.onnx` | ONNX teacher model path |
| `--long-edges` | `128` | Final bitmap long edge(s), comma-separated |
| `--teacher-scale` | `4` | Teacher runs at `long_edge * teacher_scale` before cleanup |
| `--threads` | `4` | ONNX Runtime thread count (0 = runtime default) |
| `--merge-threshold` | `60.0` | Rust cleanup palette merge threshold |
| `--max-colors` | `20` | Cleanup palette cap; use `0` to disable |
| `--smooth-passes` | `2` | Cleanup neighborhood smoothing passes |
| `--grid-refine` | `false` | Enable perfectPixel Sobel grid-boundary refinement |
| `--grid-refine-radius` | `1` | Boundary search radius, only used with `--grid-refine` |

## True Bitmap Output

- `--long-edges 128` means the final PNG long edge is 128 pixels.
- Original aspect ratio is preserved.
- No preview upscale is generated.
- The Wu teacher runs at `long_edge * 4`; a Rust cleanup pass collapses the known 4px lattice to final bitmap pixels.

Use `--grid-refine` only for externally generated pixel-style images whose grids are visibly warped or off-grid; Wu teacher output already has an exact 4px lattice. See `docs/PERFECT_PIXEL.md`.

## Architecture

```text
Input → Aspect resize to long_edge*4 → Normalize [-1,1]
    → ONNX teacher inference → Denormalize pseudo pixel art
    → Rust known-pitch cleanup (4px cells → 1 bitmap pixel)
    → True bitmap PNG
```

## Development

```bash
cargo test --workspace
cargo build --release -p pixelization-cli --bin pixelize
```

## License

- **Code**: MIT OR Apache-2.0
- **Weights**: Non-commercial research only (from upstream)

## References

- [WuZongWei6/Pixelization](https://github.com/WuZongWei6/Pixelization) - Original PyTorch implementation
- [theamusing/perfectPixel](https://github.com/theamusing/perfectPixel) - MIT grid-refinement algorithm (optional mode)
