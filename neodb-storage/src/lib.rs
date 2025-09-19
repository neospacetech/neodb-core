//! Storage engine for NeoDB
//!
//! This crate provides persistent storage capabilities for NeoDB,
//! including disk-based storage, indexing, and data durability.

pub mod engine;
pub mod index;
pub mod persistence;

pub use engine::StorageEngine;
pub use index::Index;
pub use persistence::PersistenceManager;

/// Storage engine result type
pub type Result<T> = std::result::Result<T, StorageError>;

/// Storage-specific error types
#[derive(Debug, thiserror::Error)]
pub enum StorageError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
    
    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),
    
    #[error("Storage not initialized")]
    NotInitialized,
    
    #[error("Key not found: {0}")]
    KeyNotFound(String),
    
    #[error("Index error: {0}")]
    Index(String),
}