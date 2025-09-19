//! In-memory caching system for NeoDB
//!
//! This crate provides high-performance caching capabilities for NeoDB,
//! including LRU caches, concurrent access, and cache invalidation strategies.

pub mod lru;
pub mod concurrent;
pub mod manager;

pub use lru::LruCache;
pub use concurrent::ConcurrentCache;
pub use manager::CacheManager;

/// Cache result type
pub type Result<T> = std::result::Result<T, CacheError>;

/// Cache-specific error types
#[derive(Debug, thiserror::Error)]
pub enum CacheError {
    #[error("Cache miss for key: {0}")]
    Miss(String),
    
    #[error("Cache is full")]
    Full,
    
    #[error("Invalid cache state: {0}")]
    InvalidState(String),
    
    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),
}