//! Visitor pattern for graph traversal

/// Result of visiting a node during traversal
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VisitResult {
    /// Continue traversal to neighbors
    Continue,
    /// Stop the entire traversal
    Stop,
    /// Skip this node's neighbors but continue overall traversal
    Skip,
}

/// Visitor trait for graph traversal algorithms
pub trait Visitor {
    /// Called when visiting a node during traversal
    fn visit_node(&mut self, node_id: &str) -> VisitResult;

    /// Get the neighbors of a node
    fn get_neighbors(&self, node_id: &str) -> Vec<String>;

    /// Called when entering an edge (optional override)
    fn visit_edge(&mut self, _from: &str, _to: &str, _edge_type: Option<&str>) -> VisitResult {
        VisitResult::Continue
    }

    /// Called when backtracking from a node (optional override)
    fn leave_node(&mut self, _node_id: &str) {}
}

/// Simple collecting visitor that records visited nodes
#[derive(Debug, Default)]
pub struct CollectingVisitor {
    pub visited_nodes: Vec<String>,
    pub visited_edges: Vec<(String, String)>,
}

impl CollectingVisitor {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn visited_count(&self) -> usize {
        self.visited_nodes.len()
    }

    pub fn clear(&mut self) {
        self.visited_nodes.clear();
        self.visited_edges.clear();
    }
}

/// Filtering visitor that only visits nodes matching a predicate
pub struct FilteringVisitor<F, V>
where
    F: Fn(&str) -> bool,
    V: Visitor,
{
    predicate: F,
    inner_visitor: V,
}

impl<F, V> FilteringVisitor<F, V>
where
    F: Fn(&str) -> bool,
    V: Visitor,
{
    pub fn new(predicate: F, inner_visitor: V) -> Self {
        Self {
            predicate,
            inner_visitor,
        }
    }
}

impl<F, V> Visitor for FilteringVisitor<F, V>
where
    F: Fn(&str) -> bool,
    V: Visitor,
{
    fn visit_node(&mut self, node_id: &str) -> VisitResult {
        if (self.predicate)(node_id) {
            self.inner_visitor.visit_node(node_id)
        } else {
            VisitResult::Skip
        }
    }

    fn get_neighbors(&self, node_id: &str) -> Vec<String> {
        self.inner_visitor.get_neighbors(node_id)
    }

    fn visit_edge(&mut self, from: &str, to: &str, edge_type: Option<&str>) -> VisitResult {
        self.inner_visitor.visit_edge(from, to, edge_type)
    }

    fn leave_node(&mut self, node_id: &str) {
        self.inner_visitor.leave_node(node_id)
    }
}

/// Depth-limiting visitor wrapper
pub struct DepthLimitingVisitor<V>
where
    V: Visitor,
{
    inner_visitor: V,
    max_depth: usize,
    current_depth: usize,
}

impl<V> DepthLimitingVisitor<V>
where
    V: Visitor,
{
    pub fn new(inner_visitor: V, max_depth: usize) -> Self {
        Self {
            inner_visitor,
            max_depth,
            current_depth: 0,
        }
    }
}

impl<V> Visitor for DepthLimitingVisitor<V>
where
    V: Visitor,
{
    fn visit_node(&mut self, node_id: &str) -> VisitResult {
        if self.current_depth > self.max_depth {
            return VisitResult::Skip;
        }

        self.current_depth += 1;
        let result = self.inner_visitor.visit_node(node_id);
        self.current_depth -= 1;

        result
    }

    fn get_neighbors(&self, node_id: &str) -> Vec<String> {
        self.inner_visitor.get_neighbors(node_id)
    }

    fn visit_edge(&mut self, from: &str, to: &str, edge_type: Option<&str>) -> VisitResult {
        self.inner_visitor.visit_edge(from, to, edge_type)
    }

    fn leave_node(&mut self, node_id: &str) {
        self.inner_visitor.leave_node(node_id)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    struct TestGraphVisitor {
        graph: HashMap<String, Vec<String>>,
        visited: Vec<String>,
    }

    impl TestGraphVisitor {
        fn new() -> Self {
            let mut graph = HashMap::new();
            graph.insert("A".to_string(), vec!["B".to_string(), "C".to_string()]);
            graph.insert("B".to_string(), vec!["D".to_string()]);
            graph.insert("C".to_string(), vec!["D".to_string()]);
            graph.insert("D".to_string(), vec![]);

            Self {
                graph,
                visited: Vec::new(),
            }
        }
    }

    impl Visitor for TestGraphVisitor {
        fn visit_node(&mut self, node_id: &str) -> VisitResult {
            self.visited.push(node_id.to_string());
            VisitResult::Continue
        }

        fn get_neighbors(&self, node_id: &str) -> Vec<String> {
            self.graph.get(node_id).cloned().unwrap_or_default()
        }
    }

    impl Visitor for CollectingVisitor {
        fn visit_node(&mut self, node_id: &str) -> VisitResult {
            self.visited_nodes.push(node_id.to_string());
            VisitResult::Continue
        }

        fn get_neighbors(&self, _node_id: &str) -> Vec<String> {
            // This would need to be provided by the caller
            vec![]
        }
    }

    #[test]
    fn test_collecting_visitor() {
        let mut visitor = CollectingVisitor::new();

        assert_eq!(visitor.visit_node("A"), VisitResult::Continue);
        assert_eq!(visitor.visit_node("B"), VisitResult::Continue);

        assert_eq!(visitor.visited_count(), 2);
        assert!(visitor.visited_nodes.contains(&"A".to_string()));
        assert!(visitor.visited_nodes.contains(&"B".to_string()));
    }

    #[test]
    fn test_filtering_visitor() {
        let base_visitor = CollectingVisitor::new();
        let mut filtering_visitor = FilteringVisitor::new(
            |node: &str| node.starts_with('A'),
            base_visitor,
        );

        assert_eq!(filtering_visitor.visit_node("A1"), VisitResult::Continue);
        assert_eq!(filtering_visitor.visit_node("B1"), VisitResult::Skip);
    }
}