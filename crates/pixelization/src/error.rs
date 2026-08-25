use std::path::PathBuf;

#[derive(Debug, thiserror::Error)]
pub enum PixelizationError {
    #[error("cell size must be at least 1, got {0}")]
    InvalidCellSize(u32),
    #[error("model input must have rank 4 [N,C,H,W], got {0:?}")]
    InvalidModelInput(Vec<i64>),
    #[error("model must accept exactly one RGB image input, found {0}")]
    InvalidInputCount(usize),
    #[error("model input must have one batch and three channels, got {0:?}")]
    UnsupportedInputShape(Vec<i64>),
    #[error("model output must be [1,3,H,W], got {0:?}")]
    InvalidModelOutput(Vec<usize>),
    #[error("model has no output tensors")]
    MissingModelOutput,
    #[error("input image dimensions are too small after cell-size grid alignment")]
    EmptyGrid,
    #[error("output path already exists and is not a directory: {0}")]
    OutputNotDirectory(PathBuf),
}
