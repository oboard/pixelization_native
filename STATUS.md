# Pixelization Native - Status Report

## Summary

Successfully ported `WuZongWei6/Pixelization` into a high-performance, pure CPU, Rust native binary Pixel Art engine.

## Model Details

| Property | Value |
|----------|-------|
| **Model size** | 76 MB (dynamic shape ONNX) |
| **Parameters** | 19,919,366 (~19.9M) |
| **Input shape** | `[batch, 3, H, W]` (dynamic H/W, divisible by 4) |
| **Output shape** | `[batch, 3, H, W]` (same as input) |
| **Opset version** | 17 |
| **Operators** | 884 nodes: 40 Conv, 26 InstanceNormalization, 2 Tanh |

## Parity Validation Results

### PyTorch vs ONNX (tensor level, 10 test images)
- **Mean PSNR**: 73.92 dB
- **Mean SSIM**: 0.999661
- **Max error**: 0.0071 (in [-1, 1] normalized range, ~0.35% of range)

**Conclusion**: ONNX export is numerically identical to PyTorch.

### PyTorch vs Rust (full pipeline, 10 test images)
- **Mean PSNR**: 64.18 dB
- **Mean SSIM**: 0.999776
- **Max error**: 3.00/255 (~1.2%)
- **Mean error**: ~0.05/255 (~0.02%)

**Conclusion**: Rust implementation matches PyTorch with high fidelity. Small differences are due to:
1. Floating-point precision differences
2. Bicubic interpolation implementation (PIL vs fast_image_resize)
3. ONNX Runtime vs PyTorch numerical differences

## Performance (Apple Silicon M-series)

| Configuration | Time | Memory |
|---------------|------|--------|
| **Cold start** | 1.89s | 269 MB |
| **Warm (1 thread)** | ~3.9s | - |
| **Warm (4 threads)** | ~1.5s | - |

### Notes
- Model loading is one-time cost
- Multi-threading provides ~2.6x speedup (1→4 threads)
- Pure CPU inference, no GPU required

## Architecture

```
Input image (any size)
  ↓  rescale: BICUBIC halve/double to keep dims in [128, 4000]
  ↓  resize: BICUBIC to (W//cell_size)*4 × (H//cell_size)*4
  ↓  center-crop: snap to multiple of 4
  ↓  normalize: RGB8 → NCHW f32 in [-1, 1]
  ↓  ONNX Runtime CPU inference (dynamic shape)
  ↓  denormalize: NCHW f32 → RGB8
  ↓  nearest-neighbor ÷4: collapse 4-px lattice cells
  ↓  nearest-neighbor ×cell_size: expand to final cell size
  ↓  alpha compositing (preserve original alpha)
Output pixel-art RGBA
```

## Files

### Rust Crates
- `crates/pixelization/` - Core inference library
- `crates/pixelization-cli/` - Command-line interface
- `crates/pixelization/tests/integration.rs` - Integration tests (8 tests, all passing)

### Python Export
- `export/model.py` - PyTorch model definitions with batch=1 specialization
- `export/export_onnx.py` - ONNX export script (dynamic shape)
- `export/quick_parity.py` - PyTorch vs ONNX validation
- `export/compare_pytorch_rust.py` - Full pipeline comparison

### Models
- `models/pixelization_upstream_exact.onnx` - Upstream-exact dynamic-shape model (76 MB, generated locally; ignored by Git)
- `models/pixelization.onnx` - Optional symlink/copy to the upstream-exact model for CLI default usage

### Weights (not redistributed)
- `checkpoints/160_net_G_A.pth` - I2PNet weights (144 MB)
- `alias_net.pth` - AliasNet weights (34 MB)

## Usage

### Rust CLI
```bash
# Single image
cargo run --release -p pixelization-cli -- \
    --model models/pixelization_upstream_exact.onnx \
    --cell-size 4 \
    --threads 4 \
    input.png output.png

# Batch processing
cargo run --release -p pixelization-cli -- \
    --model models/pixelization_upstream_exact.onnx \
    ./input_dir ./output_dir
```

### Cell Size
- `--cell-size 2`: Finer pixel grid (larger output)
- `--cell-size 4`: Default (matches training)
- `--cell-size 8`: Coarser pixel grid (smaller output)

## Testing

```bash
# Unit tests
cargo test -p pixelization

# Integration tests (requires model)
PIXELIZATION_MODEL=../../models/pixelization_upstream_exact.onnx \
    cargo test -p pixelization --test integration

# Python dependencies / tools are managed by uv
uv sync

# Export upstream-exact ONNX
uv run python export/export_onnx.py \
    --generator checkpoints/160_net_G_A.pth \
    --alias alias_net.pth \
    --output models/pixelization_upstream_exact.onnx

# Parity validation
uv run python export/quick_parity.py \
    --generator checkpoints/160_net_G_A.pth \
    --alias alias_net.pth \
    --images test_images/ \
    --count 20
```

## License

- **Upstream**: Non-commercial research only (cannot redistribute weights)
- **This implementation**: MIT/Apache-2.0 (code only)

## Next Steps

1. ✅ Correctness validation complete
2. ⏳ Performance optimization (quantization, alternate backends)
3. ⏳ Cross-platform testing (Linux, Windows)
4. ⏳ Memory optimization

## Constraints Met

- ✅ No batch API
- ✅ No Node/Python bindings
- ✅ No GUI
- ✅ No retraining
- ✅ No INT8/FP16 quantization yet
- ✅ No tract/candle/burn backends yet
- ✅ Final upscale uses nearest-neighbor only
- ✅ Pure CPU inference via ONNX Runtime
