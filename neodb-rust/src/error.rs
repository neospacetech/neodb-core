//! Error types for NeoDB Rust core

use thiserror::Error;

/// Result type alias for NeoDB operations
pub type Result<T, E = NeoDbError> = std::result::Result<T, E>;

/// Main error type for NeoDB operations
#[derive(Error, Debug)]
pub enum NeoDbError {
    #[error("Storage error: {0}")]
    Storage(#[from] StorageError),
    
    #[error("Cache error: {0}")]
    Cache(#[from] CacheError),
    
    #[error("Traversal error: {0}")]
    Traversal(#[from] TraversalError),
    
    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),
    
    #[error("Node not found: {id}")]
    NodeNotFound { id: String },
    
    #[error("Edge not found: {id}")]
    EdgeNotFound { id: String },
    
    #[error("Node already exists: {id}")]
    NodeAlreadyExists { id: String },
    
    #[error("Edge already exists: {id}")]
    EdgeAlreadyExists { id: String },
    
    #[error("Invalid operation: {message}")]
    InvalidOperation { message: String },
    
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
    
    #[error("Generic error: {0}")]
    Generic(#[from] anyhow::Error),
}

/// Storage-specific errors
#[derive(Error, Debug)]
pub enum StorageError {
    #[error("Failed to read from storage: {0}")]
    ReadError(String),
    
    #[error("Failed to write to storage: {0}")]
    WriteError(String),
    
    #[error("Corruption detected: {0}")]
    Corruption(String),
    
    #[error("Storage not initialized")]
    NotInitialized,
}

/// Cache-specific errors
#[derive(Error, Debug)]
pub enum CacheError {
    #[error("Cache miss for key: {key}")]
    Miss { key: String },
    
    #[error("Cache full")]
    Full,
    
    #[error("Invalid cache state: {0}")]
    InvalidState(String),
}

/// Traversal-specific errors
#[derive(Error, Debug)]
pub enum TraversalError {
    #[error("Traversal depth limit exceeded: {limit}")]
    DepthLimitExceeded { limit: usize },
    
    #[error("Cycle detected in traversal")]
    CycleDetected,
    
    #[error("Invalid traversal configuration: {0}")]
    InvalidConfig(String),
}