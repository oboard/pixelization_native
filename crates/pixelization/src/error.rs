#[derive(Debug, thiserror::Error)]
pub enum PixelizationError {
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
    #[error("invalid target long edge or source dimensions for the 4px teacher lattice")]
    EmptyGrid,
}
