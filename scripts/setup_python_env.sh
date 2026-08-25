#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v uv >/dev/null 2>&1; then
  cat >&2 <<'MSG'
[setup] uv is not installed.

Install uv first:
  curl -LsSf https://astral.sh/uv/install.sh | sh

Then rerun:
  scripts/setup_python_env.sh
MSG
  exit 1
fi

echo "[setup] syncing Python environment with uv"
uv sync

echo
cat <<MSG
[setup] Python ML environment ready.

Run Python tools with uv, for example:

  uv run python export/export_onnx.py \
    --generator checkpoints/160_net_G_A.pth \
    --alias alias_net.pth \
    --output models/pixelization_upstream_exact.onnx

Weights expected locally (ignored by Git):
  alias_net.pth
  checkpoints/160_net_G_A.pth

Optional only for running upstream test_pro.py directly:
  pixelart_vgg19.pth
MSG
