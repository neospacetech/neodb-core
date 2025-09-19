//! High-level database interface for NeoDB Rust core
//!
//! This module provides the main database API that coordinates
//! storage, caching, and graph operations for optimal performance.

use std::collections::HashMap;
use serde::{Deserialize, Serialize};

use crate::graph::{Graph, Node, Edge};
use crate::error::{NeoDbError, Result};

/// Database configuration options
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DatabaseConfig {
    pub name: String,
    pub storage_path: Option<String>,
    pub cache_size: usize,
    pub enable_persistence: bool,
}

impl Default for DatabaseConfig {
    fn default() -> Self {
        Self {
            name: "neodb".to_string(),
            storage_path: None,
            cache_size: 1000,
            enable_persistence: false,
        }
    }
}

/// Main database interface for NeoDB Rust core
///
/// This provides the high-performance implementation that will replace
/// the Python MVP for production workloads.
#[derive(Debug)]
pub struct Database {
    config: DatabaseConfig,
    graph: Graph,
    metadata: HashMap<String, serde_json::Value>,
}

impl Database {
    /// Create a new database with default configuration
    pub fn new() -> Self {
        Self::with_config(DatabaseConfig::default())
    }

    /// Create a new database with custom configuration
    pub fn with_config(config: DatabaseConfig) -> Self {
        let mut metadata = HashMap::new();
        metadata.insert(
            "version".to_string(),
            serde_json::Value::String("0.1.0-rust".to_string()),
        );
        metadata.insert(
            "created_at".to_string(),
            serde_json::Value::String(chrono::Utc::now().to_rfc3339()),
        );

        Self {
            config,
            graph: Graph::new(),
            metadata,
        }
    }

    /// Create a new node in the database
    pub fn create_node(
        &mut self,
        labels: Vec<String>,
        properties: HashMap<String, serde_json::Value>,
    ) -> Result<String> {
        let mut node = Node::new();

        for label in labels {
            node.add_label(label);
        }

        for (key, value) in properties {
            node.set_property(key, value);
        }

        let node_id = node.id.clone();
        self.graph.add_node(node)?;
        Ok(node_id)
    }

    /// Create a new edge between two nodes
    pub fn create_edge(
        &mut self,
        source_id: String,
        target_id: String,
        relationship_type: String,
        properties: HashMap<String, serde_json::Value>,
    ) -> Result<String> {
        let mut edge = Edge::new(source_id, target_id, relationship_type);

        for (key, value) in properties {
            edge.set_property(key, value);
        }

        let edge_id = edge.id.clone();
        self.graph.add_edge(edge)?;
        Ok(edge_id)
    }

    /// Find nodes by label
    pub fn find_nodes(&self, label: Option<&str>) -> Vec<&Node> {
        match label {
            Some(label) => self.graph.find_nodes_by_label(label),
            None => self.graph.nodes().collect(),
        }
    }

    /// Find nodes by property
    pub fn find_nodes_by_property(
        &self,
        key: &str,
        value: &serde_json::Value,
    ) -> Vec<&Node> {
        self.graph.find_nodes_by_property(key, value)
    }

    /// Get a node by ID
    pub fn get_node(&self, node_id: &str) -> Option<&Node> {
        self.graph.get_node(node_id)
    }

    /// Get an edge by ID
    pub fn get_edge(&self, edge_id: &str) -> Option<&Edge> {
        self.graph.get_edge(edge_id)
    }

    /// Delete a node and all its edges
    pub fn delete_node(&mut self, node_id: &str) -> Result<()> {
        self.graph.remove_node(node_id)?;
        Ok(())
    }

    /// Delete an edge
    pub fn delete_edge(&mut self, edge_id: &str) -> Result<()> {
        self.graph.remove_edge(edge_id)?;
        Ok(())
    }

    /// Get neighbors of a node
    pub fn get_neighbors(&self, node_id: &str) -> Vec<&Node> {
        self.graph.get_neighbors(node_id)
    }

    /// Get edges connected to a node
    pub fn get_node_edges(&self, node_id: &str) -> Vec<&Edge> {
        let mut edges = Vec::new();
        edges.extend(self.graph.get_outgoing_edges(node_id));
        edges.extend(self.graph.get_incoming_edges(node_id));
        edges
    }

    /// Clear all data from the database
    pub fn clear(&mut self) {
        self.graph.clear();
    }

    /// Get database statistics
    pub fn stats(&self) -> HashMap<String, serde_json::Value> {
        let mut stats = HashMap::new();
        stats.insert(
            "name".to_string(),
            serde_json::Value::String(self.config.name.clone()),
        );
        stats.insert(
            "node_count".to_string(),
            serde_json::Value::Number(self.graph.node_count().into()),
        );
        stats.insert(
            "edge_count".to_string(),
            serde_json::Value::Number(self.graph.edge_count().into()),
        );
        stats.insert(
            "metadata".to_string(),
            serde_json::Value::Object(
                self.metadata
                    .iter()
                    .map(|(k, v)| (k.clone(), v.clone()))
                    .collect(),
            ),
        );
        stats
    }

    /// Get the underlying graph (read-only access)
    pub fn graph(&self) -> &Graph {
        &self.graph
    }

    /// Get database configuration
    pub fn config(&self) -> &DatabaseConfig {
        &self.config
    }
}

impl Default for Database {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_database_creation() {
        let db = Database::new();
        assert_eq!(db.graph().node_count(), 0);
        assert_eq!(db.graph().edge_count(), 0);
    }

    #[test]
    fn test_node_creation() {
        let mut db = Database::new();
        
        let mut properties = HashMap::new();
        properties.insert("name".to_string(), json!("John"));
        properties.insert("age".to_string(), json!(30));
        
        let node_id = db.create_node(vec!["Person".to_string()], properties).unwrap();
        
        let node = db.get_node(&node_id).unwrap();
        assert!(node.has_label("Person"));
        assert_eq!(node.get_property("name"), Some(&json!("John")));
        assert_eq!(node.get_property("age"), Some(&json!(30)));
    }

    #[test]
    fn test_edge_creation() {
        let mut db = Database::new();
        
        // Create two nodes
        let node1_id = db.create_node(vec!["Person".to_string()], HashMap::new()).unwrap();
        let node2_id = db.create_node(vec!["Person".to_string()], HashMap::new()).unwrap();
        
        // Create edge between them
        let mut properties = HashMap::new();
        properties.insert("since".to_string(), json!(2020));
        
        let edge_id = db.create_edge(
            node1_id.clone(),
            node2_id.clone(),
            "KNOWS".to_string(),
            properties,
        ).unwrap();
        
        let edge = db.get_edge(&edge_id).unwrap();
        assert_eq!(edge.source_id, node1_id);
        assert_eq!(edge.target_id, node2_id);
        assert_eq!(edge.relationship_type, "KNOWS");
        assert_eq!(edge.get_property("since"), Some(&json!(2020)));
    }

    #[test]
    fn test_database_stats() {
        let mut db = Database::new();
        
        db.create_node(vec!["Person".to_string()], HashMap::new()).unwrap();
        db.create_node(vec!["Company".to_string()], HashMap::new()).unwrap();
        
        let stats = db.stats();
        assert_eq!(stats.get("node_count"), Some(&json!(2)));
        assert_eq!(stats.get("edge_count"), Some(&json!(0)));
    }
}