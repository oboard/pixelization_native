#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv"

echo "[setup] creating venv at $VENV"
python3 -m venv "$VENV"
source "$VENV/bin/activate"
python -m pip install --upgrade pip wheel setuptools
python -m pip install -r "$ROOT/export/requirements.txt"

echo
cat <<MSG
[setup] Python ML environment ready.

Activate it with:
  source "$VENV/bin/activate"

Next steps:
  1. Download upstream checkpoints into:
       alias_net.pth
       checkpoints/YOUR_MODEL_NAME/160_net_G_A.pth
     (Optionally keep 160_net_G_B.pth and pixelart_vgg19.pth beside them for audit/reference.)

  2. Export ONNX:
       python export/export_onnx.py \
         --generator checkpoints/YOUR_MODEL_NAME/160_net_G_A.pth \
         --alias alias_net.pth \
         --output models/pixelization.onnx

  3. Validate parity on >=20 images:
       python export/validate_parity.py \
         --generator checkpoints/YOUR_MODEL_NAME/160_net_G_A.pth \
         --alias alias_net.pth \
         --onnx models/pixelization.onnx \
         --images ./test-images
MSG
