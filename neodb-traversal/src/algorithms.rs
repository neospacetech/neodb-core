//! Core traversal algorithms

use std::collections::{HashSet, VecDeque};
use crate::{Result, TraversalError, Visitor, VisitResult};

/// Depth-First Search traversal
#[derive(Debug)]
pub struct DepthFirstSearch {
    max_depth: Option<usize>,
    visited: HashSet<String>,
}

impl DepthFirstSearch {
    pub fn new() -> Self {
        Self {
            max_depth: None,
            visited: HashSet::new(),
        }
    }

    pub fn with_max_depth(max_depth: usize) -> Self {
        Self {
            max_depth: Some(max_depth),
            visited: HashSet::new(),
        }
    }

    pub fn traverse<V>(&mut self, start_node: &str, visitor: &mut V) -> Result<()>
    where
        V: Visitor,
    {
        self.visited.clear();
        self.dfs_recursive(start_node, visitor, 0)
    }

    fn dfs_recursive<V>(&mut self, node_id: &str, visitor: &mut V, depth: usize) -> Result<()>
    where
        V: Visitor,
    {
        if let Some(max_depth) = self.max_depth {
            if depth > max_depth {
                return Err(TraversalError::DepthLimitExceeded { limit: max_depth });
            }
        }

        if self.visited.contains(node_id) {
            return Ok(());
        }

        self.visited.insert(node_id.to_string());

        match visitor.visit_node(node_id) {
            VisitResult::Continue => {
                // Get neighbors from visitor and continue traversal
                let neighbors = visitor.get_neighbors(node_id);
                for neighbor in neighbors {
                    self.dfs_recursive(&neighbor, visitor, depth + 1)?;
                }
            }
            VisitResult::Stop => return Ok(()),
            VisitResult::Skip => {} // Skip this subtree but continue overall traversal
        }

        Ok(())
    }
}

impl Default for DepthFirstSearch {
    fn default() -> Self {
        Self::new()
    }
}

/// Breadth-First Search traversal
#[derive(Debug)]
pub struct BreadthFirstSearch {
    max_depth: Option<usize>,
}

impl BreadthFirstSearch {
    pub fn new() -> Self {
        Self { max_depth: None }
    }

    pub fn with_max_depth(max_depth: usize) -> Self {
        Self {
            max_depth: Some(max_depth),
        }
    }

    pub fn traverse<V>(&mut self, start_node: &str, visitor: &mut V) -> Result<()>
    where
        V: Visitor,
    {
        let mut queue = VecDeque::new();
        let mut visited = HashSet::new();

        queue.push_back((start_node.to_string(), 0));
        visited.insert(start_node.to_string());

        while let Some((node_id, depth)) = queue.pop_front() {
            if let Some(max_depth) = self.max_depth {
                if depth > max_depth {
                    continue;
                }
            }

            match visitor.visit_node(&node_id) {
                VisitResult::Continue => {
                    let neighbors = visitor.get_neighbors(&node_id);
                    for neighbor in neighbors {
                        if !visited.contains(&neighbor) {
                            visited.insert(neighbor.clone());
                            queue.push_back((neighbor, depth + 1));
                        }
                    }
                }
                VisitResult::Stop => break,
                VisitResult::Skip => continue,
            }
        }

        Ok(())
    }
}

impl Default for BreadthFirstSearch {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::visitor::{Visitor, VisitResult};
    use std::collections::HashMap;

    struct TestGraph {
        edges: HashMap<String, Vec<String>>,
        visited_nodes: Vec<String>,
    }

    impl TestGraph {
        fn new() -> Self {
            let mut edges = HashMap::new();
            edges.insert("A".to_string(), vec!["B".to_string(), "C".to_string()]);
            edges.insert("B".to_string(), vec!["D".to_string()]);
            edges.insert("C".to_string(), vec!["D".to_string()]);
            edges.insert("D".to_string(), vec![]);

            Self {
                edges,
                visited_nodes: Vec::new(),
            }
        }
    }

    impl Visitor for TestGraph {
        fn visit_node(&mut self, node_id: &str) -> VisitResult {
            self.visited_nodes.push(node_id.to_string());
            VisitResult::Continue
        }

        fn get_neighbors(&self, node_id: &str) -> Vec<String> {
            self.edges.get(node_id).cloned().unwrap_or_default()
        }
    }

    #[test]
    fn test_dfs_traversal() {
        let mut dfs = DepthFirstSearch::new();
        let mut graph = TestGraph::new();

        dfs.traverse("A", &mut graph).unwrap();

        assert!(!graph.visited_nodes.is_empty());
        assert!(graph.visited_nodes.contains(&"A".to_string()));
    }

    #[test]
    fn test_bfs_traversal() {
        let mut bfs = BreadthFirstSearch::new();
        let mut graph = TestGraph::new();

        bfs.traverse("A", &mut graph).unwrap();

        assert!(!graph.visited_nodes.is_empty());
        assert!(graph.visited_nodes.contains(&"A".to_string()));
    }
}