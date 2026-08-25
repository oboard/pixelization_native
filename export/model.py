"""Self-contained, test_pro-faithful Pixelization inference graph.

This file intentionally does NOT import from the upstream repository. It embeds the
minimal network definitions needed to export the Test Pro inference path:

    RGBEnc → RGBDec(fixed cell_size_code [1,2048]) → AliasNet

Excluded intentionally:
  - PBEnc / VGG-19 structure extractor  (constructor dep in upstream; never used
    by Test Pro's forwarded inference path)
  - C2PGen.forward / P2CGen / P2INet / discriminators / training code

Important upstream quirks reproduced exactly:
  - RGBDecoder.forward defines mod_conv_1..8 but actually calls mod_conv_2 for
    chunks 2..8 in upstream test_pro.py's model code.
  - ModulationConvBlock's raw OIHW → [1,k,k,in,out] view/permute layout is
    preserved for batch=1; it is not equivalent to ordinary OIHW channel scaling.
"""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

import torch
from torch import Tensor, nn
import torch.nn.functional as F


# ---------------------------------------------------------------------------
# Frozen cell-size-4 MLP input code. Copied verbatim from upstream test_pro.py.
# ---------------------------------------------------------------------------
MLP_CODE: list[float] = [
    233356.8125, -27387.5918, -32866.8008, 126575.0312, -181590.0156, -31543.1289, 50374.1289, 99631.4062,
    -188897.3750, 138322.7031, -107266.2266, 125778.5781, 42416.1836, 139710.8594, -39614.6250, -69972.6875,
    -21886.4141, 86938.4766, 31457.6270, -98892.2344, -1191.5887, -61662.1719, -180121.9062, -32931.0859,
    43109.0391, 21490.1328, -153485.3281, 94259.1797, 43103.1992, -231953.8125, 52496.7422, 142697.4062,
    -34882.7852, -98740.0625, 34458.5078, -135436.3438, 11420.5488, -18895.8984, -71195.4141, 176947.2344,
    -52747.5742, 109054.6562, -28124.9473, -17736.6152, -41327.1562, 69853.3906, 79046.2656, -3923.7344,
    -5644.5229, 96586.7578, -89315.2656, -146578.0156, -61862.1484, -83956.4375, 87574.5703, -75055.0469,
    19571.8203, 79358.7891, -16501.5000, -147169.2188, -97861.6797, 60442.1797, 40156.9023, 223136.3906,
    -81118.0547, -221443.6406, 54911.6914, 54735.9258, -58805.7305, -168884.4844, 40865.9609, -28627.9043,
    -18604.7227, 120274.6172, 49712.2383, 164402.7031, -53165.0820, -60664.0469, -97956.1484, -121468.4062,
    -69926.1484, -4889.0151, 127367.7344, 200241.0781, -85817.7578, -143190.0625, -74049.5312, 137980.5781,
    -150788.7656, -115719.6719, -189250.1250, -153069.7344, -127429.7891, -187588.2500, 125264.7422,
    -79082.3438, -114144.5781, 36033.5039, -57502.2188, 80488.1562, 36501.4570, -138817.5938, -22189.6523,
    -222146.9688, -73292.3984, 127717.2422, -183836.3750, -105907.0859, 145422.8750, 66981.2031, -9596.6699,
    78099.4922, 70226.3359, 35841.8789, -116117.6016, -150986.0156, 81622.4922, 113575.0625, 154419.4844,
    53586.4141, 118494.8750, 131625.4375, -19763.1094, 75581.1172, -42750.5039, 97934.8281, 6706.7949,
    -101179.0078, 83519.6172, -83054.8359, -56749.2578, -30683.6992, 54615.9492, 84061.1406, -229136.7188,
    -60554.0000, 8120.2622, -106468.7891, -28316.3418, -166351.3125, 47797.3984, 96013.4141, 71482.9453,
    -101429.9297, 209063.3594, -3033.6882, -38952.5352, -84920.6719, -5895.1543, -18641.8105, 47884.3633,
    -14620.0273, -132898.6719, -40903.5859, 197217.3750, -128599.1328, -115397.8906, -22670.7676, -78569.9688,
    -54559.7070, -106855.2031, 40703.1484, 55568.3164, 60202.9844, -64757.9375, -32068.8652, 160663.3438,
    72187.0703, -148519.5469, 162952.8906, -128048.2031, -136153.8906, -15270.3730, -52766.3281, -52517.4531,
    18652.1992, 195354.2188, -136657.3750, -8034.2622, -92699.6016, -129169.1406, 188479.9844, 46003.7500,
    -93383.0781, -67831.6484, -66710.5469, 104338.5234, 85878.8438, -73165.2031, 95857.3203, 71213.1250,
    94603.1094, -30359.8125, -107989.2578, 99822.1719, 184626.3594, 79238.4531, -272978.9375, -137948.5781,
    -145245.8125, 75359.2031, 26652.7930, 50421.4141, 60784.4102, -18286.3398, -182851.9531, -87178.7969,
    -13131.7539, 195674.8906, 59951.7852, 124353.7422, -36709.1758, -54575.4766, 77822.6953, 43697.4102,
    -64394.3438, 113281.1797, -93987.0703, 221989.7188, 132902.5000, -9538.8574, -14594.1338, 65084.9453,
    -12501.7227, 130330.6875, -115123.4766, 20823.0898, 75512.4922, -75255.7422, -41936.7656, -186678.8281,
    -166799.9375, 138770.6250, -78969.9531, 124516.8047, -85558.5781, -69272.4375, -115539.1094, 228774.4844,
    -76529.3281, -107735.8906, -76798.8906, -194335.2812, 56530.5742, -9397.7529, 132985.8281, 163929.8438,
    -188517.7969, -141155.6406, 45071.0391, 207788.3125, -125826.1172, 8965.3320, -159584.8438, 95842.4609,
    -76929.4688,
]
assert len(MLP_CODE) == 256, f"MLP_CODE length must be 256, got {len(MLP_CODE)}"


def _strip_module(state: Mapping[str, Tensor]) -> dict[str, Tensor]:
    """Remove DataParallel ``module.`` prefix from state dict keys."""
    return {key.removeprefix("module."): value for key, value in state.items()}


def _substate(state: dict[str, Tensor], prefix: str) -> dict[str, Tensor]:
    """Extract and strip keys beginning with ``prefix``."""
    return {key[len(prefix):]: value for key, value in state.items() if key.startswith(prefix)}


class LayerNorm(nn.Module):
    def __init__(self, num_features: int, eps: float = 1e-5, affine: bool = True) -> None:
        super().__init__()
        self.num_features = num_features
        self.affine = affine
        self.eps = eps
        if self.affine:
            self.gamma = nn.Parameter(torch.Tensor(num_features).uniform_())
            self.beta = nn.Parameter(torch.zeros(num_features))

    def forward(self, x: Tensor) -> Tensor:
        shape = [-1] + [1] * (x.dim() - 1)
        if x.size(0) == 1:
            mean = x.view(-1).mean().view(*shape)
            std = x.view(-1).std().view(*shape)
        else:
            mean = x.view(x.size(0), -1).mean(1).view(*shape)
            std = x.view(x.size(0), -1).std(1).view(*shape)
        x = (x - mean) / (std + self.eps)
        if self.affine:
            shape = [1, -1] + [1] * (x.dim() - 2)
            x = x * self.gamma.view(*shape) + self.beta.view(*shape)
        return x


class ConvBlock(nn.Module):
    def __init__(self, input_dim: int, output_dim: int, kernel_size: int, stride: int,
                 padding: int = 0, norm: str = 'none', activation: str = 'relu', pad_type: str = 'zero') -> None:
        super().__init__()
        if pad_type == 'reflect':
            self.pad = nn.ReflectionPad2d(padding)
        elif pad_type == 'replicate':
            self.pad = nn.ReplicationPad2d(padding)
        elif pad_type == 'zero':
            self.pad = nn.ZeroPad2d(padding)
        else:
            raise ValueError(f"Unsupported padding type: {pad_type}")

        if norm == 'bn':
            self.norm = nn.BatchNorm2d(output_dim)
        elif norm == 'in':
            self.norm = nn.InstanceNorm2d(output_dim)
        elif norm == 'ln':
            self.norm = LayerNorm(output_dim)
        elif norm in ('none', 'sn'):
            self.norm = None
        else:
            raise ValueError(f"Unsupported normalization: {norm}")

        if activation == 'relu':
            self.activation = nn.ReLU(inplace=True)
        elif activation == 'lrelu':
            self.activation = nn.LeakyReLU(0.2, inplace=True)
        elif activation == 'prelu':
            self.activation = nn.PReLU()
        elif activation == 'selu':
            self.activation = nn.SELU(inplace=True)
        elif activation == 'tanh':
            self.activation = nn.Tanh()
        elif activation == 'none':
            self.activation = None
        else:
            raise ValueError(f"Unsupported activation: {activation}")

        self.conv = nn.Conv2d(input_dim, output_dim, kernel_size, stride, bias=True)

    def forward(self, x: Tensor) -> Tensor:
        x = self.conv(self.pad(x))
        if self.norm:
            x = self.norm(x)
        if self.activation:
            x = self.activation(x)
        return x


class AliasConvBlock(ConvBlock):
    pass


class ResBlock(nn.Module):
    def __init__(self, dim: int, norm: str = 'in', activation: str = 'relu', pad_type: str = 'zero') -> None:
        super().__init__()
        self.model = nn.Sequential(
            ConvBlock(dim, dim, 3, 1, 1, norm=norm, activation=activation, pad_type=pad_type),
            ConvBlock(dim, dim, 3, 1, 1, norm=norm, activation='none', pad_type=pad_type),
        )

    def forward(self, x: Tensor) -> Tensor:
        return self.model(x) + x


class ResBlocks(nn.Module):
    def __init__(self, num_blocks: int, dim: int, norm: str = 'in', activation: str = 'relu', pad_type: str = 'zero') -> None:
        super().__init__()
        self.model = nn.Sequential(*[
            ResBlock(dim, norm=norm, activation=activation, pad_type=pad_type)
            for _ in range(num_blocks)
        ])

    def forward(self, x: Tensor) -> Tensor:
        return self.model(x)


class AliasResBlock(nn.Module):
    def __init__(self, dim: int, norm: str = 'in', activation: str = 'relu', pad_type: str = 'zero') -> None:
        super().__init__()
        self.model = nn.Sequential(
            AliasConvBlock(dim, dim, 3, 1, 1, norm=norm, activation=activation, pad_type=pad_type),
            AliasConvBlock(dim, dim, 3, 1, 1, norm=norm, activation='none', pad_type=pad_type),
        )

    def forward(self, x: Tensor) -> Tensor:
        return self.model(x) + x


class AliasResBlocks(nn.Module):
    def __init__(self, num_blocks: int, dim: int, norm: str = 'in', activation: str = 'relu', pad_type: str = 'zero') -> None:
        super().__init__()
        self.model = nn.Sequential(*[
            AliasResBlock(dim, norm=norm, activation=activation, pad_type=pad_type)
            for _ in range(num_blocks)
        ])

    def forward(self, x: Tensor) -> Tensor:
        return self.model(x)


class linearBlock(nn.Module):
    def __init__(self, input_dim: int, output_dim: int, norm: str = 'none', activation: str = 'relu') -> None:
        super().__init__()
        self.fc = nn.Linear(input_dim, output_dim, bias=True)
        if norm == 'bn':
            self.norm = nn.BatchNorm1d(output_dim)
        elif norm == 'in':
            self.norm = nn.InstanceNorm1d(output_dim)
        elif norm == 'ln':
            self.norm = LayerNorm(output_dim)
        elif norm in ('none', 'sn'):
            self.norm = None
        else:
            raise ValueError(f"Unsupported normalization: {norm}")

        if activation == 'relu':
            self.activation = nn.ReLU(inplace=True)
        elif activation == 'lrelu':
            self.activation = nn.LeakyReLU(0.2, inplace=True)
        elif activation == 'prelu':
            self.activation = nn.PReLU()
        elif activation == 'selu':
            self.activation = nn.SELU(inplace=True)
        elif activation == 'tanh':
            self.activation = nn.Tanh()
        elif activation == 'none':
            self.activation = None
        else:
            raise ValueError(f"Unsupported activation: {activation}")

    def forward(self, x: Tensor) -> Tensor:
        out = self.fc(x)
        if self.norm:
            out = self.norm(out)
        if self.activation:
            out = self.activation(out)
        return out


class MLP(nn.Module):
    def __init__(self, input_dim: int, output_dim: int, dim: int, n_blk: int, norm: str = 'none', activ: str = 'relu') -> None:
        super().__init__()
        layers: list[nn.Module] = [linearBlock(input_dim, input_dim, norm=norm, activation=activ)]
        layers += [linearBlock(input_dim, dim, norm=norm, activation=activ)]
        for _ in range(n_blk - 2):
            layers += [linearBlock(dim, dim, norm=norm, activation=activ)]
        layers += [linearBlock(dim, output_dim, norm='none', activation='none')]
        self.model = nn.Sequential(*layers)

    def forward(self, style0: Tensor, style1: Tensor | None = None, a: float = 0) -> Tensor:
        style1 = style0
        return self.model[3]((1 - a) * self.model[0:3](style0.view(style0.size(0), -1)) + a * self.model[0:3](style1.view(style1.size(0), -1)))


class RGBEncoder(nn.Module):
    def __init__(self, input_dim: int, dim: int, n_downsample: int, n_res: int, norm: str, activ: str, pad_type: str) -> None:
        super().__init__()
        layers: list[nn.Module] = [ConvBlock(input_dim, dim, 7, 1, 3, norm=norm, activation=activ, pad_type=pad_type)]
        for _ in range(n_downsample):
            layers += [ConvBlock(dim, 2 * dim, 4, 2, 1, norm=norm, activation=activ, pad_type=pad_type)]
            dim *= 2
        layers += [ResBlocks(n_res, dim, norm=norm, activation=activ, pad_type=pad_type)]
        self.model = nn.Sequential(*layers)
        self.output_dim = dim

    def forward(self, x: Tensor) -> Tensor:
        return self.model(x)


class ModulationConvBlockBatch1(nn.Module):
    """Upstream ModulationConvBlock specialized to batch_size=1 for ONNX export."""

    def __init__(self, input_dim: int, output_dim: int, kernel_size: int) -> None:
        super().__init__()
        self.in_c = input_dim
        self.out_c = output_dim
        self.ksize = kernel_size
        self.stride = 1
        self.padding = kernel_size // 2
        self.eps = 1e-8
        fan_in = kernel_size * kernel_size * input_dim
        self.wscale = 1.0 / (fan_in ** 0.5)
        self.weight = nn.Parameter(torch.randn(output_dim, input_dim, kernel_size, kernel_size))
        self.bias = nn.Parameter(torch.zeros(output_dim))
        self.activate = nn.LeakyReLU(negative_slope=0.2, inplace=True)
        self.activate_scale = 2.0 ** 0.5

    def forward(self, x: Tensor, code: Tensor) -> Tensor:
        batch = 1
        height = x.shape[2]
        width = x.shape[3]
        weight = self.weight * self.wscale
        weight = weight.view(1, self.ksize, self.ksize, self.in_c, self.out_c)
        weight = weight * code.view(batch, 1, 1, self.in_c, 1)
        weight_norm = torch.sqrt(torch.sum(weight ** 2, dim=[1, 2, 3]) + self.eps)
        weight = weight / weight_norm.view(batch, 1, 1, 1, self.out_c)
        x = x.view(1, batch * self.in_c, height, width)
        weight = weight.permute(1, 2, 3, 0, 4).reshape(self.ksize, self.ksize, self.in_c, batch * self.out_c)
        weight = weight.permute(3, 2, 0, 1)
        out = F.conv2d(x, weight=weight, bias=None, stride=self.stride, padding=self.padding, groups=batch)
        out = out.view(batch, self.out_c, height, width)
        out = out + self.bias.view(1, -1, 1, 1)
        out = self.activate(out) * self.activate_scale
        return out


class RGBDecoderBatch1(nn.Module):
    def __init__(self, dim: int, output_dim: int, n_upsample: int, n_res: int, res_norm: str, activ: str = 'relu', pad_type: str = 'zero') -> None:
        super().__init__()
        self.mod_conv_1 = ModulationConvBlockBatch1(256, 256, 3)
        self.mod_conv_2 = ModulationConvBlockBatch1(256, 256, 3)
        self.mod_conv_3 = ModulationConvBlockBatch1(256, 256, 3)
        self.mod_conv_4 = ModulationConvBlockBatch1(256, 256, 3)
        self.mod_conv_5 = ModulationConvBlockBatch1(256, 256, 3)
        self.mod_conv_6 = ModulationConvBlockBatch1(256, 256, 3)
        self.mod_conv_7 = ModulationConvBlockBatch1(256, 256, 3)
        self.mod_conv_8 = ModulationConvBlockBatch1(256, 256, 3)
        self.upsample_block1 = nn.Upsample(scale_factor=2, mode='nearest')
        self.conv_1 = ConvBlock(dim, dim // 2, 5, 1, 2, norm='ln', activation=activ, pad_type=pad_type)
        dim //= 2
        self.upsample_block2 = nn.Upsample(scale_factor=2, mode='nearest')
        self.conv_2 = ConvBlock(dim, dim // 2, 5, 1, 2, norm='ln', activation=activ, pad_type=pad_type)
        dim //= 2
        self.conv_3 = ConvBlock(dim, output_dim, 7, 1, 3, norm='none', activation='tanh', pad_type=pad_type)

    def forward(self, x: Tensor, code: Tensor) -> Tensor:
        residual = x
        x = self.mod_conv_1(x, code[:, :256])
        x = self.mod_conv_2(x, code[:, 256:512])
        x = x + residual
        residual = x
        x = self.mod_conv_2(x, code[:, 512:768])
        x = self.mod_conv_2(x, code[:, 768:1024])
        x = x + residual
        residual = x
        x = self.mod_conv_2(x, code[:, 1024:1280])
        x = self.mod_conv_2(x, code[:, 1280:1536])
        x = x + residual
        residual = x
        x = self.mod_conv_2(x, code[:, 1536:1792])
        x = self.mod_conv_2(x, code[:, 1792:2048])
        x = x + residual
        x = self.upsample_block1(x)
        x = self.conv_1(x)
        x = self.upsample_block2(x)
        x = self.conv_2(x)
        x = self.conv_3(x)
        return x


class AliasRGBEncoder(nn.Module):
    def __init__(self, input_dim: int, dim: int, n_downsample: int, n_res: int, norm: str, activ: str, pad_type: str) -> None:
        super().__init__()
        layers: list[nn.Module] = [AliasConvBlock(input_dim, dim, 7, 1, 3, norm=norm, activation=activ, pad_type=pad_type)]
        for _ in range(n_downsample):
            layers += [AliasConvBlock(dim, 2 * dim, 4, 2, 1, norm=norm, activation=activ, pad_type=pad_type)]
            dim *= 2
        layers += [AliasResBlocks(n_res, dim, norm=norm, activation=activ, pad_type=pad_type)]
        self.model = nn.Sequential(*layers)
        self.output_dim = dim

    def forward(self, x: Tensor) -> Tensor:
        return self.model(x)


class AliasRGBDecoder(nn.Module):
    def __init__(self, dim: int, output_dim: int, n_upsample: int, n_res: int, res_norm: str, activ: str = 'relu', pad_type: str = 'zero') -> None:
        super().__init__()
        self.Res_Blocks = AliasResBlocks(n_res, dim, res_norm, activ, pad_type=pad_type)
        self.upsample_block1 = nn.Upsample(scale_factor=2, mode='nearest')
        self.conv_1 = AliasConvBlock(dim, dim // 2, 5, 1, 2, norm='ln', activation=activ, pad_type=pad_type)
        dim //= 2
        self.upsample_block2 = nn.Upsample(scale_factor=2, mode='nearest')
        self.conv_2 = AliasConvBlock(dim, dim // 2, 5, 1, 2, norm='ln', activation=activ, pad_type=pad_type)
        dim //= 2
        self.conv_3 = AliasConvBlock(dim, output_dim, 7, 1, 3, norm='none', activation='tanh', pad_type=pad_type)

    def forward(self, x: Tensor) -> Tensor:
        x = self.Res_Blocks(x)
        x = self.upsample_block1(x)
        x = self.conv_1(x)
        x = self.upsample_block2(x)
        x = self.conv_2(x)
        x = self.conv_3(x)
        return x


class AliasNet(nn.Module):
    def __init__(self, input_dim: int, output_dim: int, dim: int, n_downsample: int, n_res: int, activ: str = 'relu', pad_type: str = 'reflect') -> None:
        super().__init__()
        self.RGBEnc = AliasRGBEncoder(input_dim, dim, n_downsample, n_res, 'in', activ, pad_type=pad_type)
        self.RGBDec = AliasRGBDecoder(self.RGBEnc.output_dim, output_dim, n_downsample, n_res, res_norm='in', activ=activ, pad_type=pad_type)

    def forward(self, x: Tensor) -> Tensor:
        return self.RGBDec(self.RGBEnc(x))


class TestProInference(nn.Module):
    """Exact upstream test_pro.py neural path, exportable to ONNX at batch=1."""

    def __init__(self, generator_checkpoint: Path, alias_checkpoint: Path) -> None:
        super().__init__()
        self.rgb_encoder = RGBEncoder(3, 64, 2, 4, 'in', 'relu', pad_type='reflect')
        self.rgb_decoder = RGBDecoderBatch1(256, 3, 2, 4, res_norm='adain', activ='relu', pad_type='reflect')
        self.alias = AliasNet(3, 3, 64, 2, 3, activ='relu', pad_type='reflect')
        mlp = MLP(256, 2048, 256, 3, norm='none', activ='relu')

        gen_state = _strip_module(torch.load(generator_checkpoint, map_location='cpu', weights_only=True))
        self.rgb_encoder.load_state_dict(_substate(gen_state, 'RGBEnc.'), strict=True)
        dec_state: dict[str, Tensor] = {}
        for i in range(1, 9):
            for p in ('weight', 'bias'):
                key = f'RGBDec.mod_conv_{i}.{p}'
                if key in gen_state:
                    dec_state[f'mod_conv_{i}.{p}'] = gen_state[key]
        for name, param in gen_state.items():
            if name.startswith('RGBDec.conv_'):
                dec_state[name[7:]] = param
        self.rgb_decoder.load_state_dict(dec_state, strict=True)
        mlp.load_state_dict(_substate(gen_state, 'MLP.'), strict=True)

        alias_state = _strip_module(torch.load(alias_checkpoint, map_location='cpu', weights_only=True))
        self.alias.load_state_dict(alias_state, strict=True)

        code = torch.tensor(MLP_CODE, dtype=torch.float32).reshape(1, 256, 1, 1)
        with torch.inference_mode():
            cell_size_code = mlp(code)
        assert cell_size_code.shape == (1, 2048), cell_size_code.shape
        self.register_buffer('cell_size_code', cell_size_code, persistent=True)

    def forward(self, image: Tensor) -> Tensor:
        feat = self.rgb_encoder(image)
        decoded = self.rgb_decoder(feat, self.cell_size_code)
        return self.alias(decoded)
