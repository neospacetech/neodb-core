//! Python FFI bindings for NeoDB Rust core
//!
//! This crate provides Python bindings for the high-performance Rust
//! components of NeoDB, enabling seamless integration between the
//! Python MVP and Rust performance core.

use pyo3::prelude::*;
use std::collections::HashMap;

// Re-export the main Rust types
use neodb_rust::{Graph as RustGraph, Node as RustNode, Edge as RustEdge, Database as RustDatabase};

/// Python wrapper for the Rust Graph
#[pyclass(name = "RustGraph")]
pub struct PyGraph {
    inner: RustGraph,
}

#[pymethods]
impl PyGraph {
    #[new]
    fn new() -> Self {
        Self {
            inner: RustGraph::new(),
        }
    }

    fn node_count(&self) -> usize {
        self.inner.node_count()
    }

    fn edge_count(&self) -> usize {
        self.inner.edge_count()
    }

    fn add_node(&mut self, node_id: String, labels: Vec<String>, properties: HashMap<String, String>) -> PyResult<String> {
        let mut node = RustNode::with_id(node_id);
        
        for label in labels {
            node.add_label(label);
        }
        
        for (key, value) in properties {
            node.set_property(key, serde_json::Value::String(value));
        }
        
        self.inner.add_node(node)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Failed to add node: {}", e)))
    }

    fn add_edge(&mut self, source_id: String, target_id: String, relationship_type: String, properties: HashMap<String, String>) -> PyResult<String> {
        let mut edge = RustEdge::new(source_id, target_id, relationship_type);
        
        for (key, value) in properties {
            edge.set_property(key, serde_json::Value::String(value));
        }
        
        self.inner.add_edge(edge)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Failed to add edge: {}", e)))
    }

    fn clear(&mut self) {
        self.inner.clear();
    }
}

/// Python wrapper for the Rust Database
#[pyclass(name = "RustDatabase")]
pub struct PyDatabase {
    inner: RustDatabase,
}

#[pymethods]
impl PyDatabase {
    #[new]
    fn new() -> Self {
        Self {
            inner: RustDatabase::new(),
        }
    }

    fn create_node(&mut self, labels: Vec<String>, properties: HashMap<String, String>) -> PyResult<String> {
        let mut props = HashMap::new();
        for (key, value) in properties {
            props.insert(key, serde_json::Value::String(value));
        }
        
        self.inner.create_node(labels, props)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Failed to create node: {}", e)))
    }

    fn create_edge(&mut self, source_id: String, target_id: String, relationship_type: String, properties: HashMap<String, String>) -> PyResult<String> {
        let mut props = HashMap::new();
        for (key, value) in properties {
            props.insert(key, serde_json::Value::String(value));
        }
        
        self.inner.create_edge(source_id, target_id, relationship_type, props)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Failed to create edge: {}", e)))
    }

    fn stats(&self) -> HashMap<String, String> {
        let stats = self.inner.stats();
        let mut result = HashMap::new();
        
        for (key, value) in stats {
            result.insert(key, value.to_string());
        }
        
        result
    }

    fn clear(&mut self) {
        self.inner.clear();
    }
}

/// Performance benchmark functions
#[pyfunction]
fn benchmark_graph_creation(node_count: usize, edge_count: usize) -> PyResult<f64> {
    use std::time::Instant;
    
    let start = Instant::now();
    
    let mut graph = RustGraph::new();
    
    // Add nodes
    for i in 0..node_count {
        let node = RustNode::with_id(format!("node_{}", i));
        graph.add_node(node).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Failed to add node: {}", e))
        })?;
    }
    
    // Add edges
    for i in 0..edge_count {
        let source_id = format!("node_{}", i % node_count);
        let target_id = format!("node_{}", (i + 1) % node_count);
        let edge = RustEdge::new(source_id, target_id, "CONNECTED".to_string());
        graph.add_edge(edge).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Failed to add edge: {}", e))
        })?;
    }
    
    let duration = start.elapsed();
    Ok(duration.as_secs_f64())
}

/// Module initialization function
#[pymodule]
fn neodb_ffi(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<PyGraph>()?;
    m.add_class::<PyDatabase>()?;
    m.add_function(wrap_pyfunction!(benchmark_graph_creation, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_py_graph_creation() {
        let graph = PyGraph::new();
        assert_eq!(graph.node_count(), 0);
        assert_eq!(graph.edge_count(), 0);
    }

    #[test]
    fn test_py_database_creation() {
        let db = PyDatabase::new();
        let stats = db.stats();
        assert!(stats.contains_key("node_count"));
        assert!(stats.contains_key("edge_count"));
    }
}