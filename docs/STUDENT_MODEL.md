# <10MB Low-resolution Student Model Plan

Goal: specialize Pixelization Native for any-size input to `<=128×128` pixel-art outputs with a deployment ONNX below 10MB.

## Constraints

- Keep upstream teacher weights unchanged.
- Keep FP32 for the baseline student.
- ONNX Runtime CPU backend.
- No INT8/FP16 as the primary path.
- Target visual quality over maximum speed.

## Student architecture

Implemented in `export/student_model.py`:

- Fully convolutional encoder/body/decoder.
- Default `width=32`, `blocks=4`.
- Input/output: `[N, 3, H, W]` in `[-1, 1]`.
- Host-side final nearest-neighbor pixel-grid postprocess remains unchanged.

Parameter budget:

| Width | Params | Raw FP32 payload |
|---:|---:|---:|
| 16 | 379,475 | 1.45 MiB |
| 24 | 848,763 | 3.24 MiB |
| 32 | 1,504,419 | 5.74 MiB |
| 40 | 2,346,443 | 8.95 MiB |
| 48 | 3,374,835 | 12.87 MiB |

Default `width=32` exports to ~5.7MB ONNX, safely under 10MB.

## Scripts

### Export untrained/trained student ONNX

```bash
uv run python export/export_student_onnx.py \
  --checkpoint checkpoints/student_lowres.pth \
  --output models/pixelization_student.onnx \
  --width 32 \
  --blocks 4 \
  --size 128
```

Omit `--checkpoint` for an untrained smoke-test export.

### Prepare the upstream pixel_art.zip dataset

```bash
uv run python export/prepare_pixel_art_dataset.py \
  --zip /Users/oboard/Downloads/pixel_art.zip \
  --output data/pixel_art_split \
  --val-ratio 0.1 \
  --seed 42 \
  --force
```

Observed split from `/Users/oboard/Downloads/pixel_art.zip`:

```text
train/non_pixel: 3811
val/non_pixel:   424
train/multi_cell/{2..8}: 900 each
val/multi_cell/{2..8}:   100 each
```

For the first student pass, use `train/non_pixel` for teacher distillation. The
`multi_cell` directories are useful later as pixel-art style/reference data, but
are not one-to-one paired with `non_pixel` by filename.

### Train by distillation

```bash
uv run python export/train_student.py \
  --images data/pixel_art_split/train/non_pixel \
  --generator checkpoints/160_net_G_A.pth \
  --alias alias_net.pth \
  --output checkpoints/student_lowres.pth \
  --resolution 128 \
  --width 32 \
  --blocks 4 \
  --steps 20000 \
  --device mps
```

The teacher is the upstream-exact model in `export/model.py`; no upstream source checkout is required.

### Validate teacher vs student

```bash
uv run python export/validate_student.py \
  --images /path/to/validation/images \
  --student models/pixelization_student.onnx \
  --resolution 128 \
  --limit 20 \
  --output-dir outputs/student_validation \
  --report outputs/student_validation/report.json
```

### Benchmark student ONNX with the Rust lowres bench hook

```bash
target/release/lowres-bench \
  --model models/pixelization_student.onnx \
  --threads 4 \
  --iterations 50 \
  --resolutions 128,96,64,56,48,32 \
  --output-dir outputs/student_lowres \
  /path/to/image.png
```

## Smoke-test status

Verified locally:

```text
student params: 1,504,419 (5.74 MiB raw FP32)
models/pixelization_student_untrained.onnx: ~5.7MB
models/pixelization_student_smoke.onnx: ~5.8MB after 5 CPU smoke-training steps
```

Smoke validation against teacher on 2 images at 128px completed and wrote:

```text
outputs/student_validation_smoke/report.json
outputs/student_validation_smoke/1_128.png
outputs/student_validation_smoke/10_128.png
```

The 5-step smoke model is only to verify the pipeline; it is not a quality model.
A real quality pass needs a larger dataset and substantially more training steps.

Smoke Rust/ONNX Runtime CPU benchmark for the student hook:

| Resolution | Inference p50 | Total p50 | Peak RSS |
|---:|---:|---:|---:|
| 128 | 25.04 ms | 25.44 ms | 67.0 MB |
| 64 | 7.37 ms | 7.61 ms | 67.0 MB |
| 32 | 3.24 ms | 3.44 ms | 67.1 MB |
