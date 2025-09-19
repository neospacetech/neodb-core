//! High-performance graph data structures for NeoDB
//!
//! This module provides the Rust implementation of core graph components
//! that will replace the Python MVP for performance-critical operations.

use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use uuid::Uuid;

use crate::error::{NeoDbError, Result};

/// A node in the graph with labels and properties
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Node {
    pub id: String,
    pub labels: HashSet<String>,
    pub properties: HashMap<String, serde_json::Value>,
}

impl Node {
    /// Create a new node with a generated UUID
    pub fn new() -> Self {
        Self {
            id: Uuid::new_v4().to_string(),
            labels: HashSet::new(),
            properties: HashMap::new(),
        }
    }

    /// Create a new node with a specific ID
    pub fn with_id(id: String) -> Self {
        Self {
            id,
            labels: HashSet::new(),
            properties: HashMap::new(),
        }
    }

    /// Add a label to this node
    pub fn add_label(&mut self, label: String) {
        self.labels.insert(label);
    }

    /// Remove a label from this node
    pub fn remove_label(&mut self, label: &str) -> bool {
        self.labels.remove(label)
    }

    /// Check if node has a specific label
    pub fn has_label(&self, label: &str) -> bool {
        self.labels.contains(label)
    }

    /// Set a property on this node
    pub fn set_property(&mut self, key: String, value: serde_json::Value) {
        self.properties.insert(key, value);
    }

    /// Get a property from this node
    pub fn get_property(&self, key: &str) -> Option<&serde_json::Value> {
        self.properties.get(key)
    }

    /// Remove a property from this node
    pub fn remove_property(&mut self, key: &str) -> Option<serde_json::Value> {
        self.properties.remove(key)
    }
}

impl Default for Node {
    fn default() -> Self {
        Self::new()
    }
}

/// An edge connecting two nodes with a relationship type and properties
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Edge {
    pub id: String,
    pub source_id: String,
    pub target_id: String,
    pub relationship_type: String,
    pub properties: HashMap<String, serde_json::Value>,
}

impl Edge {
    /// Create a new edge with generated UUID
    pub fn new(source_id: String, target_id: String, relationship_type: String) -> Self {
        Self {
            id: Uuid::new_v4().to_string(),
            source_id,
            target_id,
            relationship_type,
            properties: HashMap::new(),
        }
    }

    /// Create a new edge with specific ID
    pub fn with_id(
        id: String,
        source_id: String,
        target_id: String,
        relationship_type: String,
    ) -> Self {
        Self {
            id,
            source_id,
            target_id,
            relationship_type,
            properties: HashMap::new(),
        }
    }

    /// Set a property on this edge
    pub fn set_property(&mut self, key: String, value: serde_json::Value) {
        self.properties.insert(key, value);
    }

    /// Get a property from this edge
    pub fn get_property(&self, key: &str) -> Option<&serde_json::Value> {
        self.properties.get(key)
    }

    /// Remove a property from this edge
    pub fn remove_property(&mut self, key: &str) -> Option<serde_json::Value> {
        self.properties.remove(key)
    }
}

/// High-performance in-memory graph implementation
///
/// This will serve as the foundation for the Rust-based performance core,
/// eventually backed by persistent storage and advanced caching.
#[derive(Debug, Default)]
pub struct Graph {
    nodes: HashMap<String, Node>,
    edges: HashMap<String, Edge>,
    // Adjacency lists for efficient traversal
    outgoing_edges: HashMap<String, HashSet<String>>, // node_id -> edge_ids
    incoming_edges: HashMap<String, HashSet<String>>, // node_id -> edge_ids
}

impl Graph {
    /// Create a new empty graph
    pub fn new() -> Self {
        Self::default()
    }

    /// Add a node to the graph
    pub fn add_node(&mut self, node: Node) -> Result<String> {
        let node_id = node.id.clone();
        
        if self.nodes.contains_key(&node_id) {
            return Err(NeoDbError::NodeAlreadyExists { id: node_id });
        }

        self.nodes.insert(node_id.clone(), node);
        self.outgoing_edges.insert(node_id.clone(), HashSet::new());
        self.incoming_edges.insert(node_id.clone(), HashSet::new());

        Ok(node_id)
    }

    /// Get a node by ID
    pub fn get_node(&self, node_id: &str) -> Option<&Node> {
        self.nodes.get(node_id)
    }

    /// Get a mutable reference to a node by ID
    pub fn get_node_mut(&mut self, node_id: &str) -> Option<&mut Node> {
        self.nodes.get_mut(node_id)
    }

    /// Remove a node and all its connected edges
    pub fn remove_node(&mut self, node_id: &str) -> Result<Node> {
        let node = self.nodes.remove(node_id)
            .ok_or_else(|| NeoDbError::NodeNotFound { id: node_id.to_string() })?;

        // Remove all connected edges
        if let Some(outgoing) = self.outgoing_edges.remove(node_id) {
            for edge_id in outgoing {
                self.edges.remove(&edge_id);
            }
        }

        if let Some(incoming) = self.incoming_edges.remove(node_id) {
            for edge_id in incoming {
                self.edges.remove(&edge_id);
            }
        }

        // Clean up adjacency lists for other nodes
        for edge_set in self.outgoing_edges.values_mut() {
            edge_set.retain(|edge_id| self.edges.contains_key(edge_id));
        }
        for edge_set in self.incoming_edges.values_mut() {
            edge_set.retain(|edge_id| self.edges.contains_key(edge_id));
        }

        Ok(node)
    }

    /// Add an edge to the graph
    pub fn add_edge(&mut self, edge: Edge) -> Result<String> {
        let edge_id = edge.id.clone();
        
        if self.edges.contains_key(&edge_id) {
            return Err(NeoDbError::EdgeAlreadyExists { id: edge_id });
        }

        // Verify source and target nodes exist
        if !self.nodes.contains_key(&edge.source_id) {
            return Err(NeoDbError::NodeNotFound { id: edge.source_id.clone() });
        }
        if !self.nodes.contains_key(&edge.target_id) {
            return Err(NeoDbError::NodeNotFound { id: edge.target_id.clone() });
        }

        // Update adjacency lists
        self.outgoing_edges
            .entry(edge.source_id.clone())
            .or_default()
            .insert(edge_id.clone());

        self.incoming_edges
            .entry(edge.target_id.clone())
            .or_default()
            .insert(edge_id.clone());

        self.edges.insert(edge_id.clone(), edge);

        Ok(edge_id)
    }

    /// Get an edge by ID
    pub fn get_edge(&self, edge_id: &str) -> Option<&Edge> {
        self.edges.get(edge_id)
    }

    /// Get a mutable reference to an edge by ID
    pub fn get_edge_mut(&mut self, edge_id: &str) -> Option<&mut Edge> {
        self.edges.get_mut(edge_id)
    }

    /// Remove an edge from the graph
    pub fn remove_edge(&mut self, edge_id: &str) -> Result<Edge> {
        let edge = self.edges.remove(edge_id)
            .ok_or_else(|| NeoDbError::EdgeNotFound { id: edge_id.to_string() })?;

        // Update adjacency lists
        if let Some(outgoing) = self.outgoing_edges.get_mut(&edge.source_id) {
            outgoing.remove(edge_id);
        }
        if let Some(incoming) = self.incoming_edges.get_mut(&edge.target_id) {
            incoming.remove(edge_id);
        }

        Ok(edge)
    }

    /// Get all outgoing edges for a node
    pub fn get_outgoing_edges(&self, node_id: &str) -> Vec<&Edge> {
        self.outgoing_edges
            .get(node_id)
            .map(|edge_ids| {
                edge_ids
                    .iter()
                    .filter_map(|edge_id| self.edges.get(edge_id))
                    .collect()
            })
            .unwrap_or_default()
    }

    /// Get all incoming edges for a node
    pub fn get_incoming_edges(&self, node_id: &str) -> Vec<&Edge> {
        self.incoming_edges
            .get(node_id)
            .map(|edge_ids| {
                edge_ids
                    .iter()
                    .filter_map(|edge_id| self.edges.get(edge_id))
                    .collect()
            })
            .unwrap_or_default()
    }

    /// Get all neighbors (connected nodes) for a node
    pub fn get_neighbors(&self, node_id: &str) -> Vec<&Node> {
        let mut neighbors = Vec::new();

        // Add nodes connected via outgoing edges
        if let Some(outgoing) = self.outgoing_edges.get(node_id) {
            for edge_id in outgoing {
                if let Some(edge) = self.edges.get(edge_id) {
                    if let Some(neighbor) = self.nodes.get(&edge.target_id) {
                        neighbors.push(neighbor);
                    }
                }
            }
        }

        // Add nodes connected via incoming edges
        if let Some(incoming) = self.incoming_edges.get(node_id) {
            for edge_id in incoming {
                if let Some(edge) = self.edges.get(edge_id) {
                    if let Some(neighbor) = self.nodes.get(&edge.source_id) {
                        neighbors.push(neighbor);
                    }
                }
            }
        }

        neighbors
    }

    /// Find nodes by label
    pub fn find_nodes_by_label(&self, label: &str) -> Vec<&Node> {
        self.nodes
            .values()
            .filter(|node| node.has_label(label))
            .collect()
    }

    /// Find nodes by property value
    pub fn find_nodes_by_property(
        &self,
        key: &str,
        value: &serde_json::Value,
    ) -> Vec<&Node> {
        self.nodes
            .values()
            .filter(|node| {
                node.get_property(key)
                    .map(|prop_value| prop_value == value)
                    .unwrap_or(false)
            })
            .collect()
    }

    /// Get the number of nodes in the graph
    pub fn node_count(&self) -> usize {
        self.nodes.len()
    }

    /// Get the number of edges in the graph
    pub fn edge_count(&self) -> usize {
        self.edges.len()
    }

    /// Get all nodes in the graph
    pub fn nodes(&self) -> impl Iterator<Item = &Node> {
        self.nodes.values()
    }

    /// Get all edges in the graph
    pub fn edges(&self) -> impl Iterator<Item = &Edge> {
        self.edges.values()
    }

    /// Clear all nodes and edges from the graph
    pub fn clear(&mut self) {
        self.nodes.clear();
        self.edges.clear();
        self.outgoing_edges.clear();
        self.incoming_edges.clear();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_node_creation() {
        let mut node = Node::new();
        assert!(!node.id.is_empty());
        
        node.add_label("Person".to_string());
        assert!(node.has_label("Person"));
        
        node.set_property("name".to_string(), serde_json::Value::String("John".to_string()));
        assert_eq!(node.get_property("name"), Some(&serde_json::Value::String("John".to_string())));
    }

    #[test]
    fn test_graph_operations() {
        let mut graph = Graph::new();
        
        let node1 = Node::with_id("1".to_string());
        let node2 = Node::with_id("2".to_string());
        
        graph.add_node(node1).unwrap();
        graph.add_node(node2).unwrap();
        
        let edge = Edge::new("1".to_string(), "2".to_string(), "KNOWS".to_string());
        graph.add_edge(edge).unwrap();
        
        assert_eq!(graph.node_count(), 2);
        assert_eq!(graph.edge_count(), 1);
        
        let neighbors = graph.get_neighbors("1");
        assert_eq!(neighbors.len(), 1);
        assert_eq!(neighbors[0].id, "2");
    }
}