# Pixelization Native

High-performance, pure CPU, Rust native binary Pixel Art engine. Port of [WuZongWei6/Pixelization](https://github.com/WuZongWei6/Pixelization).

## Features

- **Pure CPU inference** via ONNX Runtime
- **Dynamic input size** - any image size divisible by 4
- **Cross-platform** - macOS (ARM64/x86_64), Linux (ARM64/x86_64), Windows (x86_64)
- **High fidelity** - PSNR 48.90 dB vs PyTorch reference
- **Fast** - ~1.5s for 512x512 image on 4 threads (Apple Silicon)

## Quick Start

### 1. Download Weights

```bash
# From Google Drive (see upstream repo for links)
# Place files at:
#   checkpoints/160_net_G_A.pth (144 MB)
#   alias_net.pth (34 MB)
```

### 2. Export ONNX Model

```bash
python -m venv .venv
source .venv/bin/activate
pip install torch onnx onnxruntime scikit-image

python export/export_onnx.py \
    --generator checkpoints/160_net_G_A.pth \
    --alias alias_net.pth \
    --output models/pixelization.onnx
```

### 3. Run

```bash
# Build
cargo build --release

# Single image
cargo run --release -p pixelization-cli -- \
    input.png output.png \
    --cell-size 4 \
    --threads 4

# Batch processing
cargo run --release -p pixelization-cli -- \
    ./input_dir ./output_dir
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--model` | `models/pixelization.onnx` | ONNX model path |
| `--cell-size` | `4` | Pixel cell size (2-8) |
| `--threads` | `0` (all cores) | ONNX Runtime thread count |

## Cell Size

The `--cell-size` parameter controls the final pixel grid resolution:

- **cell-size=2**: Finer grid, larger output
- **cell-size=4**: Default, matches training
- **cell-size=8**: Coarser grid, smaller output

The network always operates at a 4-pixel lattice; cell-size only affects pre/post resize geometry.

## Performance

| Platform | Threads | Time (512x512) |
|----------|---------|----------------|
| Apple Silicon M-series | 1 | ~3.9s |
| Apple Silicon M-series | 4 | ~1.5s |

Memory: ~270 MB (including model)

## Architecture

```
Input → Rescale [128,4000] → Resize → Crop (÷4) → Normalize [-1,1]
    → ONNX Inference → Denormalize → Nearest ÷4 → Nearest ×cell_size → Output
```

## Development

```bash
# Run tests
cargo test

# Integration tests (requires model)
PIXELIZATION_MODEL=models/pixelization.onnx cargo test --test integration

# Benchmarks
PIXELIZATION_MODEL=models/pixelization.onnx cargo bench
```

## License

- **Code**: MIT OR Apache-2.0
- **Weights**: Non-commercial research only (from upstream)

## References

- [WuZongWei6/Pixelization](https://github.com/WuZongWei6/Pixelization) - Original PyTorch implementation
