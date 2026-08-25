"""Small student model for <=128px Pixelization distillation.

This is intentionally independent from the original 19.9M-parameter teacher.
Target deployment:
  - any high-resolution input is resized/cropped by host code to <=128 model input
  - FP32 ONNX Runtime CPU
  - ONNX file size <10MB

The student predicts the teacher's upstream-exact tensor output at the same low
resolution. Final pixel-grid down/up sampling remains host-side nearest-neighbor.
"""
from __future__ import annotations

import torch
from torch import Tensor, nn
import torch.nn.functional as F


class ConvINAct(nn.Module):
    def __init__(self, in_ch: int, out_ch: int, k: int = 3, s: int = 1, act: bool = True) -> None:
        super().__init__()
        p = k // 2
        self.conv = nn.Conv2d(in_ch, out_ch, k, s, p, bias=True)
        self.norm = nn.InstanceNorm2d(out_ch, affine=True)
        self.act = nn.ReLU(inplace=True) if act else nn.Identity()

    def forward(self, x: Tensor) -> Tensor:
        return self.act(self.norm(self.conv(x)))


class ResBlock(nn.Module):
    def __init__(self, ch: int) -> None:
        super().__init__()
        self.conv1 = ConvINAct(ch, ch, 3, 1, True)
        self.conv2 = ConvINAct(ch, ch, 3, 1, False)

    def forward(self, x: Tensor) -> Tensor:
        return F.relu(x + self.conv2(self.conv1(x)), inplace=True)


class PixelizationStudent(nn.Module):
    """Tiny fully-convolutional pixelization student.

    Default width=32 keeps FP32 ONNX comfortably below 10MB while retaining enough
    capacity for <=128px teacher distillation.
    """

    def __init__(self, width: int = 32, blocks: int = 4) -> None:
        super().__init__()
        c = width
        self.stem = ConvINAct(3, c, 7, 1, True)
        self.down1 = ConvINAct(c, c * 2, 4, 2, True)
        self.down2 = ConvINAct(c * 2, c * 4, 4, 2, True)
        self.body = nn.Sequential(*[ResBlock(c * 4) for _ in range(blocks)])
        self.up1 = ConvINAct(c * 4 + c * 2, c * 2, 3, 1, True)
        self.up2 = ConvINAct(c * 2 + c, c, 3, 1, True)
        self.head = nn.Sequential(
            nn.Conv2d(c, c, 3, 1, 1),
            nn.ReLU(inplace=True),
            nn.Conv2d(c, 3, 7, 1, 3),
            nn.Tanh(),
        )

    def forward(self, x: Tensor) -> Tensor:
        s0 = self.stem(x)
        s1 = self.down1(s0)
        z = self.down2(s1)
        z = self.body(z)
        z = F.interpolate(z, size=s1.shape[-2:], mode="nearest")
        z = self.up1(torch.cat([z, s1], dim=1))
        z = F.interpolate(z, size=s0.shape[-2:], mode="nearest")
        z = self.up2(torch.cat([z, s0], dim=1))
        return self.head(z)


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())


if __name__ == "__main__":
    for width in (16, 24, 32, 40, 48):
        m = PixelizationStudent(width=width)
        n = count_parameters(m)
        print(f"width={width}: params={n:,}, fp32_size={n * 4 / 1024 / 1024:.2f} MiB")
