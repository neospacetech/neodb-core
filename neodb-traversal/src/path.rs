//! Path finding algorithms

use std::collections::{HashMap, HashSet, VecDeque};
use crate::{Result, TraversalError};

/// Represents a path between nodes
#[derive(Debug, Clone)]
pub struct Path {
    pub nodes: Vec<String>,
    pub total_cost: f64,
}

impl Path {
    pub fn new() -> Self {
        Self {
            nodes: Vec::new(),
            total_cost: 0.0,
        }
    }

    pub fn with_nodes(nodes: Vec<String>) -> Self {
        Self {
            nodes,
            total_cost: 0.0,
        }
    }

    pub fn len(&self) -> usize {
        self.nodes.len()
    }

    pub fn is_empty(&self) -> bool {
        self.nodes.is_empty()
    }

    pub fn add_node(&mut self, node: String, cost: f64) {
        self.nodes.push(node);
        self.total_cost += cost;
    }
}

impl Default for Path {
    fn default() -> Self {
        Self::new()
    }
}

/// Path finding algorithms
#[derive(Debug)]
pub struct PathFinder {
    max_depth: Option<usize>,
}

impl PathFinder {
    pub fn new() -> Self {
        Self { max_depth: None }
    }

    pub fn with_max_depth(max_depth: usize) -> Self {
        Self {
            max_depth: Some(max_depth),
        }
    }

    /// Find shortest path between two nodes using BFS
    pub fn find_shortest_path<F>(
        &self,
        start: &str,
        end: &str,
        get_neighbors: F,
    ) -> Result<Option<Path>>
    where
        F: Fn(&str) -> Vec<String>,
    {
        if start == end {
            return Ok(Some(Path::with_nodes(vec![start.to_string()])));
        }

        let mut queue = VecDeque::new();
        let mut visited = HashSet::new();
        let mut parent: HashMap<String, String> = HashMap::new();

        queue.push_back((start.to_string(), 0));
        visited.insert(start.to_string());

        while let Some((current, depth)) = queue.pop_front() {
            if let Some(max_depth) = self.max_depth {
                if depth >= max_depth {
                    continue;
                }
            }

            if current == end {
                // Reconstruct path
                let mut path_nodes = Vec::new();
                let mut current_node = end.to_string();

                path_nodes.push(current_node.clone());

                while let Some(prev_node) = parent.get(&current_node) {
                    path_nodes.push(prev_node.clone());
                    current_node = prev_node.clone();
                }

                path_nodes.reverse();
                return Ok(Some(Path::with_nodes(path_nodes)));
            }

            for neighbor in get_neighbors(&current) {
                if !visited.contains(&neighbor) {
                    visited.insert(neighbor.clone());
                    parent.insert(neighbor.clone(), current.clone());
                    queue.push_back((neighbor, depth + 1));
                }
            }
        }

        Ok(None)
    }

    /// Find all paths between two nodes (limited by depth)
    pub fn find_all_paths<F>(
        &self,
        start: &str,
        end: &str,
        get_neighbors: F,
    ) -> Result<Vec<Path>>
    where
        F: Fn(&str) -> Vec<String>,
    {
        let mut paths = Vec::new();
        let mut current_path = Path::new();
        let mut visited = HashSet::new();

        self.find_all_paths_recursive(
            start,
            end,
            &get_neighbors,
            &mut current_path,
            &mut visited,
            &mut paths,
            0,
        )?;

        Ok(paths)
    }

    fn find_all_paths_recursive<F>(
        &self,
        current: &str,
        end: &str,
        get_neighbors: &F,
        current_path: &mut Path,
        visited: &mut HashSet<String>,
        all_paths: &mut Vec<Path>,
        depth: usize,
    ) -> Result<()>
    where
        F: Fn(&str) -> Vec<String>,
    {
        if let Some(max_depth) = self.max_depth {
            if depth > max_depth {
                return Ok(());
            }
        }

        current_path.add_node(current.to_string(), 1.0);
        visited.insert(current.to_string());

        if current == end {
            all_paths.push(current_path.clone());
        } else {
            for neighbor in get_neighbors(current) {
                if !visited.contains(&neighbor) {
                    self.find_all_paths_recursive(
                        &neighbor,
                        end,
                        get_neighbors,
                        current_path,
                        visited,
                        all_paths,
                        depth + 1,
                    )?;
                }
            }
        }

        // Backtrack
        current_path.nodes.pop();
        current_path.total_cost -= 1.0;
        visited.remove(current);

        Ok(())
    }
}

impl Default for PathFinder {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn create_test_graph() -> HashMap<String, Vec<String>> {
        let mut graph = HashMap::new();
        graph.insert("A".to_string(), vec!["B".to_string(), "C".to_string()]);
        graph.insert("B".to_string(), vec!["D".to_string()]);
        graph.insert("C".to_string(), vec!["D".to_string()]);
        graph.insert("D".to_string(), vec![]);
        graph
    }

    #[test]
    fn test_shortest_path() {
        let graph = create_test_graph();
        let path_finder = PathFinder::new();

        let get_neighbors = |node: &str| -> Vec<String> {
            graph.get(node).cloned().unwrap_or_default()
        };

        let path = path_finder
            .find_shortest_path("A", "D", get_neighbors)
            .unwrap()
            .unwrap();

        assert_eq!(path.nodes.len(), 3);
        assert_eq!(path.nodes[0], "A");
        assert_eq!(path.nodes[2], "D");
    }

    #[test]
    fn test_no_path() {
        let graph = create_test_graph();
        let path_finder = PathFinder::new();

        let get_neighbors = |node: &str| -> Vec<String> {
            graph.get(node).cloned().unwrap_or_default()
        };

        let path = path_finder
            .find_shortest_path("D", "A", get_neighbors)
            .unwrap();

        assert!(path.is_none());
    }
}