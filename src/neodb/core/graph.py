"""Basic graph data structures for NeoDB MVP.

This module provides the foundational graph components that will later
be backed by the Rust performance core.
"""

from typing import Any, Dict, List, Optional, Set, Union
from dataclasses import dataclass, field
import uuid


@dataclass
class Node:
    """Represents a node in the graph."""
    
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    labels: Set[str] = field(default_factory=set)
    properties: Dict[str, Any] = field(default_factory=dict)
    
    def add_label(self, label: str) -> None:
        """Add a label to this node."""
        self.labels.add(label)
    
    def remove_label(self, label: str) -> None:
        """Remove a label from this node."""
        self.labels.discard(label)
    
    def has_label(self, label: str) -> bool:
        """Check if node has a specific label."""
        return label in self.labels
    
    def set_property(self, key: str, value: Any) -> None:
        """Set a property on this node."""
        self.properties[key] = value
    
    def get_property(self, key: str, default: Any = None) -> Any:
        """Get a property from this node."""
        return self.properties.get(key, default)
    
    def __str__(self) -> str:
        labels_str = ":".join(sorted(self.labels)) if self.labels else ""
        return f"({self.id}:{labels_str} {self.properties})"


@dataclass
class Edge:
    """Represents an edge in the graph."""
    
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_id: str = ""
    target_id: str = ""
    relationship_type: str = ""
    properties: Dict[str, Any] = field(default_factory=dict)
    
    def set_property(self, key: str, value: Any) -> None:
        """Set a property on this edge."""
        self.properties[key] = value
    
    def get_property(self, key: str, default: Any = None) -> Any:
        """Get a property from this edge."""
        return self.properties.get(key, default)
    
    def __str__(self) -> str:
        return f"({self.source_id})-[:{self.relationship_type} {self.properties}]->({self.target_id})"


class Graph:
    """In-memory graph implementation for NeoDB MVP.
    
    This will be replaced/enhanced by the Rust core for performance.
    """
    
    def __init__(self) -> None:
        self._nodes: Dict[str, Node] = {}
        self._edges: Dict[str, Edge] = {}
        self._node_edges: Dict[str, Set[str]] = {}  # node_id -> set of edge_ids
    
    def add_node(self, node: Node) -> str:
        """Add a node to the graph."""
        if node.id in self._nodes:
            raise ValueError(f"Node with id {node.id} already exists")
        
        self._nodes[node.id] = node
        self._node_edges[node.id] = set()
        return node.id
    
    def get_node(self, node_id: str) -> Optional[Node]:
        """Get a node by its ID."""
        return self._nodes.get(node_id)
    
    def remove_node(self, node_id: str) -> bool:
        """Remove a node and all its edges."""
        if node_id not in self._nodes:
            return False
        
        # Remove all edges connected to this node
        edge_ids_to_remove = list(self._node_edges[node_id])
        for edge_id in edge_ids_to_remove:
            self.remove_edge(edge_id)
        
        del self._nodes[node_id]
        del self._node_edges[node_id]
        return True
    
    def add_edge(self, edge: Edge) -> str:
        """Add an edge to the graph."""
        if edge.source_id not in self._nodes:
            raise ValueError(f"Source node {edge.source_id} does not exist")
        if edge.target_id not in self._nodes:
            raise ValueError(f"Target node {edge.target_id} does not exist")
        
        if edge.id in self._edges:
            raise ValueError(f"Edge with id {edge.id} already exists")
        
        self._edges[edge.id] = edge
        self._node_edges[edge.source_id].add(edge.id)
        self._node_edges[edge.target_id].add(edge.id)
        return edge.id
    
    def get_edge(self, edge_id: str) -> Optional[Edge]:
        """Get an edge by its ID."""
        return self._edges.get(edge_id)
    
    def remove_edge(self, edge_id: str) -> bool:
        """Remove an edge from the graph."""
        if edge_id not in self._edges:
            return False
        
        edge = self._edges[edge_id]
        self._node_edges[edge.source_id].discard(edge_id)
        self._node_edges[edge.target_id].discard(edge_id)
        del self._edges[edge_id]
        return True
    
    def get_neighbors(self, node_id: str) -> List[Node]:
        """Get all neighboring nodes."""
        if node_id not in self._nodes:
            return []
        
        neighbors = []
        for edge_id in self._node_edges[node_id]:
            edge = self._edges[edge_id]
            other_id = edge.target_id if edge.source_id == node_id else edge.source_id
            if other_id in self._nodes:
                neighbors.append(self._nodes[other_id])
        
        return neighbors
    
    def get_edges_for_node(self, node_id: str) -> List[Edge]:
        """Get all edges connected to a node."""
        if node_id not in self._nodes:
            return []
        
        return [self._edges[edge_id] for edge_id in self._node_edges[node_id]]
    
    def find_nodes_by_label(self, label: str) -> List[Node]:
        """Find all nodes with a specific label."""
        return [node for node in self._nodes.values() if node.has_label(label)]
    
    def find_nodes_by_property(self, key: str, value: Any) -> List[Node]:
        """Find all nodes with a specific property value."""
        return [
            node for node in self._nodes.values() 
            if node.get_property(key) == value
        ]
    
    @property
    def node_count(self) -> int:
        """Get the number of nodes in the graph."""
        return len(self._nodes)
    
    @property
    def edge_count(self) -> int:
        """Get the number of edges in the graph."""
        return len(self._edges)
    
    def __str__(self) -> str:
        return f"Graph(nodes={self.node_count}, edges={self.edge_count})"