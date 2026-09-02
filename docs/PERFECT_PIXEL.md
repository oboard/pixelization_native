# perfectPixel Grid Refinement Port

This project includes a compact Rust adaptation of the useful grid-refinement part of [`theamusing/perfectPixel`](https://github.com/theamusing/perfectPixel).

## Upstream license and scope

`perfectPixel` is licensed under MIT (its `pyproject.toml` declares `license = { text = "MIT" }`).

The upstream pipeline consists of:

1. FFT grid-size estimation;
2. Sobel edge detection and grid-boundary refinement;
3. per-cell image sampling.

## Rust adaptation

Our WuZongWei6 teacher runs at a known exact 4px lattice, so automatic FFT grid-size detection is both unnecessary and less reliable than the known geometry. The Rust implementation therefore ports the useful second and third stages only:

- grayscale conversion;
- 3×3 Sobel edge-energy projections;
- local maximum search around nominal grid boundaries;
- median sampling from each refined cell.

Implementation: `crates/pixelization/src/cleanup.rs`.

## CLI use

```bash
# Normal Wu teacher path: exact known 4px lattice (recommended/default)
pixelize input.png output.png --long-edges 128

# perfectPixel-style Sobel boundary alignment for externally produced,
# visibly warped or off-grid pixel-style imagery
pixelize input.png output.png --long-edges 128 --grid-refine --grid-refine-radius 1
```

`--grid-refine` is deliberately off by default. On the known Wu teacher lattice, no boundary movement produces the best fidelity. The refinement mode is for inputs with irregular or shifted grid lines.

## Validation

On the 12-image local test set at long edges 128, 56, and 32, the default fixed-grid path generated 36 true-bitmap RGB PNGs with the expected aspect-preserved dimensions. Default palette counts were 8–19 colors at 128px long edge (mean 13.5), eliminating the previous hundreds-of-near-colors artifact.

The optional Sobel-refinement probe was also exercised at all three sizes. It is fast (roughly 0.7–9ms cleanup on the demonstrated image) but it should only be enabled where grid distortion is actually visible.
