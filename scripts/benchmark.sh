#!/bin/bash
# Simple performance test for Rust pixelization
# Usage: ./scripts/benchmark.sh [model_path] [threads...]

set -e

MODEL="${1:-models/pixelization.onnx}"
THREADS="${2:-1 2 4 8}"
TEST_IMAGE="test_images/test_1.png"

if [ ! -f "$MODEL" ]; then
    echo "Model not found: $MODEL"
    exit 1
fi

if [ ! -f "$TEST_IMAGE" ]; then
    echo "Creating test image..."
    mkdir -p test_images
    convert -size 512x512 plasma:gray -seed 1 "$TEST_IMAGE" 2>/dev/null || \
        echo "ImageMagick not available, using existing image"
fi

echo "=============================================="
echo "Pixelization Performance Benchmark"
echo "=============================================="
echo "Model: $MODEL"
echo "Test image: $TEST_IMAGE"
echo ""

# Get model info
echo "--- Model Info ---"
ls -lh "$MODEL"
echo ""

# Cold start (first load)
echo "--- Cold Start ---"
/usr/bin/time -l cargo run --release -p pixelization-cli -- \
    --model "$MODEL" \
    --threads 4 \
    "$TEST_IMAGE" \
    /tmp/cold_start.png 2>&1 | grep -E "(real|size)"
echo ""

# Warm inference with different thread counts
for t in $THREADS; do
    echo "--- Threads: $t ---"
    for i in 1 2 3; do
        /usr/bin/time -p cargo run --release -p pixelization-cli -- \
            --model "$MODEL" \
            --threads $t \
            "$TEST_IMAGE" \
            /tmp/warm_${t}_${i}.png 2>&1 | grep real
    done
    echo ""
done

echo "=============================================="
echo "Benchmark complete"
echo "=============================================="
