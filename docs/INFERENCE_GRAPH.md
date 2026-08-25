# Inference graph audit

Audited upstream revision: `dc6d3b16f34c0329ac025f36924de6bae85d1490`.

## Test Pro is the deployment target

`test_pro.py` is the current direct CLI. Its actual neural graph is:

```text
normalized RGB [-1,1]
  → C2PGen.RGBEnc
  → C2PGen.RGBDec(fixed cell_size_code)
  → AliasNet
  → RGB [-1,1]
```

The frozen 256-value `MLP_code` is passed through C2PGen's MLP once at model load. `cell_size` **is not a neural network input**. The live graph does not run `C2PGen.PBEnc`.

| Artifact | Role in Test Pro | Keep in deployment ONNX? |
|---|---|---:|
| `160_net_G_A.pth` / I2PNet / C2PGen | RGB encoder/decoder + MLP | Yes, but only live submodules |
| `alias_net.pth` / AliasNet | final antialias refiner | Yes |
| `pixelart_vgg19.pth` | PBEnc/VGG constructor dependency; not forwarded by Test Pro | No |
| `160_net_G_B.pth` / P2INet / P2CGen | reverse CycleGAN generator | No |
| discriminators | training only | No |

`prepare_data.py` belongs to the older `test.py` CycleGAN flow, not Test Pro.

## Exact host preprocessing/postprocessing

1. Upstream rescales originals by repeated **BICUBIC** halves/doubles into the 128–4000px range.
2. It resizes to `(W // cell_size * 4, H // cell_size * 4)` with BICUBIC, centre-crops to a multiple of four, then maps RGB `[0,255] → [-1,1]` NCHW.
3. Model output maps `[-1,1] → uint8`, downsamples by fixed 4 with **NEAREST**, then enlarges by `cell_size` with **NEAREST**.

Thus every inference runs at the trained 4px lattice. Larger cells first reduce semantic input resolution and finally enlarge those cells. Never use linear/bicubic/Lanczos for the final two resize stages.

## Export caveat

The live decoder has batch-specialized modulation/grouped convolution. Export batch 1 and static `[1,3,512,512]`; validate the real exported graph over >=20 images before relying on it. `export/model.py` avoids constructing upstream `C2PGen`, which otherwise eagerly loads the VGG checkpoint even though its branch is dead for Test Pro.
