"""Tests for core graph data structures."""

import pytest
from neodb.core.graph import Graph, Node, Edge


class TestNode:
    """Test Node class."""
    
    def test_create_node(self):
        """Test node creation."""
        node = Node()
        assert node.id is not None
        assert isinstance(node.labels, set)
        assert isinstance(node.properties, dict)
    
    def test_node_labels(self):
        """Test node label operations."""
        node = Node()
        
        # Add labels
        node.add_label("Person")
        node.add_label("User")
        assert node.has_label("Person")
        assert node.has_label("User")
        assert "Person" in node.labels
        assert "User" in node.labels
        
        # Remove label
        node.remove_label("User")
        assert not node.has_label("User")
        assert node.has_label("Person")
    
    def test_node_properties(self):
        """Test node property operations."""
        node = Node()
        
        # Set properties
        node.set_property("name", "John")
        node.set_property("age", 30)
        
        assert node.get_property("name") == "John"
        assert node.get_property("age") == 30
        assert node.get_property("missing") is None
        assert node.get_property("missing", "default") == "default"
    
    def test_node_str(self):
        """Test node string representation."""
        node = Node()
        node.add_label("Person")
        node.set_property("name", "John")
        
        str_repr = str(node)
        assert node.id in str_repr
        assert "Person" in str_repr
        assert "name" in str_repr


class TestEdge:
    """Test Edge class."""
    
    def test_create_edge(self):
        """Test edge creation."""
        edge = Edge()
        assert edge.id is not None
        assert isinstance(edge.properties, dict)
    
    def test_edge_properties(self):
        """Test edge property operations."""
        edge = Edge(source_id="1", target_id="2", relationship_type="KNOWS")
        
        edge.set_property("since", 2020)
        edge.set_property("strength", 0.8)
        
        assert edge.get_property("since") == 2020
        assert edge.get_property("strength") == 0.8
        assert edge.get_property("missing") is None
    
    def test_edge_str(self):
        """Test edge string representation."""
        edge = Edge(source_id="1", target_id="2", relationship_type="KNOWS")
        edge.set_property("since", 2020)
        
        str_repr = str(edge)
        assert "1" in str_repr
        assert "2" in str_repr
        assert "KNOWS" in str_repr
        assert "since" in str_repr


class TestGraph:
    """Test Graph class."""
    
    def test_create_graph(self):
        """Test graph creation."""
        graph = Graph()
        assert graph.node_count == 0
        assert graph.edge_count == 0
    
    def test_add_node(self):
        """Test adding nodes to graph."""
        graph = Graph()
        node = Node()
        
        node_id = graph.add_node(node)
        assert node_id == node.id
        assert graph.node_count == 1
        assert graph.get_node(node.id) == node
    
    def test_add_duplicate_node(self):
        """Test adding duplicate nodes raises error."""
        graph = Graph()
        node = Node(id="test")
        
        graph.add_node(node)
        with pytest.raises(ValueError):
            graph.add_node(node)
    
    def test_remove_node(self):
        """Test removing nodes from graph."""
        graph = Graph()
        node = Node()
        
        graph.add_node(node)
        assert graph.node_count == 1
        
        result = graph.remove_node(node.id)
        assert result is True
        assert graph.node_count == 0
        assert graph.get_node(node.id) is None
        
        # Try removing non-existent node
        result = graph.remove_node("non-existent")
        assert result is False
    
    def test_add_edge(self):
        """Test adding edges to graph."""
        graph = Graph()
        node1 = Node(id="1")
        node2 = Node(id="2")
        
        graph.add_node(node1)
        graph.add_node(node2)
        
        edge = Edge(source_id="1", target_id="2", relationship_type="KNOWS")
        edge_id = graph.add_edge(edge)
        
        assert edge_id == edge.id
        assert graph.edge_count == 1
        assert graph.get_edge(edge.id) == edge
    
    def test_add_edge_missing_nodes(self):
        """Test adding edge with missing nodes raises error."""
        graph = Graph()
        edge = Edge(source_id="1", target_id="2", relationship_type="KNOWS")
        
        with pytest.raises(ValueError):
            graph.add_edge(edge)
    
    def test_remove_edge(self):
        """Test removing edges from graph."""
        graph = Graph()
        node1 = Node(id="1")
        node2 = Node(id="2")
        
        graph.add_node(node1)
        graph.add_node(node2)
        
        edge = Edge(source_id="1", target_id="2", relationship_type="KNOWS")
        graph.add_edge(edge)
        
        assert graph.edge_count == 1
        
        result = graph.remove_edge(edge.id)
        assert result is True
        assert graph.edge_count == 0
        assert graph.get_edge(edge.id) is None
    
    def test_get_neighbors(self):
        """Test getting node neighbors."""
        graph = Graph()
        node1 = Node(id="1")
        node2 = Node(id="2")
        node3 = Node(id="3")
        
        graph.add_node(node1)
        graph.add_node(node2)
        graph.add_node(node3)
        
        # Connect node1 to node2 and node3
        edge1 = Edge(source_id="1", target_id="2", relationship_type="KNOWS")
        edge2 = Edge(source_id="1", target_id="3", relationship_type="LIKES")
        
        graph.add_edge(edge1)
        graph.add_edge(edge2)
        
        neighbors = graph.get_neighbors("1")
        assert len(neighbors) == 2
        assert node2 in neighbors
        assert node3 in neighbors
    
    def test_get_edges_for_node(self):
        """Test getting edges for a node."""
        graph = Graph()
        node1 = Node(id="1")
        node2 = Node(id="2")
        
        graph.add_node(node1)
        graph.add_node(node2)
        
        edge = Edge(source_id="1", target_id="2", relationship_type="KNOWS")
        graph.add_edge(edge)
        
        edges = graph.get_edges_for_node("1")
        assert len(edges) == 1
        assert edge in edges
    
    def test_find_nodes_by_label(self):
        """Test finding nodes by label."""
        graph = Graph()
        
        node1 = Node(id="1")
        node1.add_label("Person")
        
        node2 = Node(id="2")
        node2.add_label("Person")
        node2.add_label("User")
        
        node3 = Node(id="3")
        node3.add_label("Company")
        
        graph.add_node(node1)
        graph.add_node(node2)
        graph.add_node(node3)
        
        person_nodes = graph.find_nodes_by_label("Person")
        assert len(person_nodes) == 2
        assert node1 in person_nodes
        assert node2 in person_nodes
        
        user_nodes = graph.find_nodes_by_label("User")
        assert len(user_nodes) == 1
        assert node2 in user_nodes
    
    def test_find_nodes_by_property(self):
        """Test finding nodes by property."""
        graph = Graph()
        
        node1 = Node(id="1")
        node1.set_property("age", 25)
        
        node2 = Node(id="2")
        node2.set_property("age", 30)
        
        node3 = Node(id="3")
        node3.set_property("age", 25)
        
        graph.add_node(node1)
        graph.add_node(node2)
        graph.add_node(node3)
        
        young_nodes = graph.find_nodes_by_property("age", 25)
        assert len(young_nodes) == 2
        assert node1 in young_nodes
        assert node3 in young_nodes
    
    def test_remove_node_with_edges(self):
        """Test removing node removes its edges."""
        graph = Graph()
        node1 = Node(id="1")
        node2 = Node(id="2")
        
        graph.add_node(node1)
        graph.add_node(node2)
        
        edge = Edge(source_id="1", target_id="2", relationship_type="KNOWS")
        graph.add_edge(edge)
        
        assert graph.node_count == 2
        assert graph.edge_count == 1
        
        graph.remove_node("1")
        
        assert graph.node_count == 1
        assert graph.edge_count == 0  # Edge should be removed too