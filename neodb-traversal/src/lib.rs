//! Graph traversal algorithms for NeoDB
//!
//! This crate provides high-performance graph traversal algorithms
//! including DFS, BFS, shortest path, and advanced graph algorithms.

pub mod algorithms;
pub mod path;
pub mod visitor;

pub use algorithms::{DepthFirstSearch, BreadthFirstSearch};
pub use path::{Path, PathFinder};
pub use visitor::{Visitor, VisitResult};

/// Traversal result type
pub type Result<T> = std::result::Result<T, TraversalError>;

/// Traversal-specific error types
#[derive(Debug, thiserror::Error)]
pub enum TraversalError {
    #[error("Traversal depth limit exceeded: {limit}")]
    DepthLimitExceeded { limit: usize },
    
    #[error("Cycle detected in traversal")]
    CycleDetected,
    
    #[error("Invalid traversal configuration: {0}")]
    InvalidConfig(String),
    
    #[error("Node not found: {0}")]
    NodeNotFound(String),
    
    #[error("No path found between nodes")]
    NoPathFound,
}