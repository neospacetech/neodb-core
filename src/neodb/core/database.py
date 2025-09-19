"""Database interface for NeoDB MVP.

This module provides the main database interface that coordinates
graph operations, query execution, and will later integrate with
the Rust performance core.
"""

from typing import Any, Dict, List, Optional
from .graph import Graph, Node, Edge


class Database:
    """Main database interface for NeoDB.
    
    This class provides the high-level API for interacting with NeoDB,
    coordinating between the Python MVP components and the future Rust core.
    """
    
    def __init__(self, name: str = "neodb") -> None:
        self.name = name
        self.graph = Graph()
        self._metadata: Dict[str, Any] = {
            "version": "0.1.0-mvp",
            "created_at": None,
            "last_modified": None,
        }
    
    def create_node(self, labels: Optional[List[str]] = None, 
                   properties: Optional[Dict[str, Any]] = None) -> Node:
        """Create a new node in the database."""
        node = Node()
        
        if labels:
            for label in labels:
                node.add_label(label)
        
        if properties:
            for key, value in properties.items():
                node.set_property(key, value)
        
        self.graph.add_node(node)
        return node
    
    def create_edge(self, source_node: Node, target_node: Node,
                   relationship_type: str,
                   properties: Optional[Dict[str, Any]] = None) -> Edge:
        """Create a new edge between two nodes."""
        edge = Edge(
            source_id=source_node.id,
            target_id=target_node.id,
            relationship_type=relationship_type
        )
        
        if properties:
            for key, value in properties.items():
                edge.set_property(key, value)
        
        self.graph.add_edge(edge)
        return edge
    
    def find_nodes(self, label: Optional[str] = None,
                  properties: Optional[Dict[str, Any]] = None) -> List[Node]:
        """Find nodes by label and/or properties."""
        if label and properties:
            # Find by both label and properties
            label_nodes = self.graph.find_nodes_by_label(label)
            return [
                node for node in label_nodes
                if all(node.get_property(k) == v for k, v in properties.items())
            ]
        elif label:
            return self.graph.find_nodes_by_label(label)
        elif properties:
            # Find by properties only
            nodes = []
            for key, value in properties.items():
                matching_nodes = self.graph.find_nodes_by_property(key, value)
                if not nodes:
                    nodes = matching_nodes
                else:
                    # Intersection of results
                    nodes = [n for n in nodes if n in matching_nodes]
            return nodes
        else:
            # Return all nodes if no filters
            return list(self.graph._nodes.values())
    
    def get_node(self, node_id: str) -> Optional[Node]:
        """Get a node by its ID."""
        return self.graph.get_node(node_id)
    
    def get_edge(self, edge_id: str) -> Optional[Edge]:
        """Get an edge by its ID."""
        return self.graph.get_edge(edge_id)
    
    def delete_node(self, node_id: str) -> bool:
        """Delete a node and all its edges."""
        return self.graph.remove_node(node_id)
    
    def delete_edge(self, edge_id: str) -> bool:
        """Delete an edge."""
        return self.graph.remove_edge(edge_id)
    
    def get_neighbors(self, node: Node) -> List[Node]:
        """Get all neighboring nodes of a given node."""
        return self.graph.get_neighbors(node.id)
    
    def get_node_edges(self, node: Node) -> List[Edge]:
        """Get all edges connected to a node."""
        return self.graph.get_edges_for_node(node.id)
    
    def clear(self) -> None:
        """Clear all data from the database."""
        self.graph = Graph()
    
    def stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        return {
            "name": self.name,
            "node_count": self.graph.node_count,
            "edge_count": self.graph.edge_count,
            "metadata": self._metadata.copy(),
        }
    
    def __str__(self) -> str:
        return f"Database(name={self.name}, {self.graph})"