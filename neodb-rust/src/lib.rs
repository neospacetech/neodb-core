//! NeoDB Rust Core Library
//!
//! This crate provides the performance-critical core components for NeoDB,
//! including graph data structures, algorithms, and storage interfaces
//! that will replace the Python MVP components for production use.

pub mod graph;
pub mod database;
pub mod error;

// Re-export main types
pub use graph::{Node, Edge, Graph};
pub use database::Database;
pub use error::{Result, NeoDbError};

// External crate dependencies
pub use neodb_storage as storage;
pub use neodb_cache as cache;
pub use neodb_traversal as traversal;

/// Version information for the Rust core
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_version() {
        assert!(!VERSION.is_empty());
    }
}