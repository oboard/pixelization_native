# Pixelization Native

使用 Rust 和 ONNX Runtime 在 CPU 上复刻 [WuZongWei6/Pixelization](https://github.com/WuZongWei6/Pixelization) 的 Test Pro 推理效果。

## 目标

- 保留上游生成器、固定风格码和 AliasNet 的完整推理链路
- 保持上游 `cell_size`、尺寸预处理和最近邻像素网格语义
- 运行时仅依赖 Rust 程序与 ONNX Runtime，支持 macOS、Linux 和 Windows
- 参考 `normalize_pixels.py`，无损收缩到最小最近邻逻辑网格
- 不添加调色板压缩、平滑或低分辨率学生模型

## 准备模型

从上游项目获取以下权重：

```text
checkpoints/160_net_G_A.pth
alias_net.pth
```

安装 Python 导出环境并生成 ONNX：

```bash
uv sync
uv run python export/export_onnx.py \
  --generator checkpoints/160_net_G_A.pth \
  --alias alias_net.pth \
  --output models/pixelization.onnx
```

导出的 ONNX 已包含生成器和 AliasNet，Rust 运行时不会再追加图像风格后处理。

## 构建与运行

```bash
cargo build --release -p pixelization-cli --bin pixelize

target/release/pixelize input.png output.png
target/release/pixelize input.png output.png --cell-size 8 --threads 4
target/release/pixelize input_dir output_dir --cell-size 4
```

参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--model` | `models/pixelization.onnx` | ONNX 模型路径 |
| `--cell-size` | `4` | 最终像素块边长，与上游参数一致 |
| `--threads` | `0` | ONNX Runtime CPU 线程数，`0` 使用默认值 |

## 推理流程

```text
输入图片转 RGB
  → 按上游规则将尺寸约束到 128～4000
  → 根据 cell_size 缩放到内部 4px 网格
  → RGB 归一化到 [-1, 1]
  → ONNX CPU 推理（Generator + AliasNet）
  → 反归一化为 RGB
  → 最近邻缩小 4 倍得到逻辑像素
  → 最近邻放大到 cell_size
  → 无损寻找最小最近邻逻辑网格
  → 输出逻辑像素图
```

## 验证

```bash
cargo fmt --all -- --check
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings

uv run python export/validate_parity.py \
  --generator checkpoints/160_net_G_A.pth \
  --alias alias_net.pth \
  --onnx models/pixelization.onnx \
  --images test_images
```

## 许可

本项目代码使用 Apache-2.0
