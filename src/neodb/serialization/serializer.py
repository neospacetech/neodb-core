"""Object serialization system for NeoDB.

This module provides serialization capabilities for graph objects,
supporting multiple formats for persistence and data exchange.
"""

import json
import pickle
from typing import Any, Dict, List, Protocol, Union
from abc import ABC, abstractmethod
from ..core.graph import Graph, Node, Edge


class SerializationFormat(Protocol):
    """Protocol for serialization formats."""
    
    def serialize(self, obj: Any) -> bytes:
        """Serialize an object to bytes."""
        ...
    
    def deserialize(self, data: bytes) -> Any:
        """Deserialize bytes to an object."""
        ...


class JSONFormat:
    """JSON serialization format."""
    
    def serialize(self, obj: Any) -> bytes:
        """Serialize an object to JSON bytes."""
        if hasattr(obj, 'to_dict'):
            data = obj.to_dict()
        else:
            data = self._convert_to_serializable(obj)
        
        return json.dumps(data, indent=2, default=str).encode('utf-8')
    
    def deserialize(self, data: bytes) -> Any:
        """Deserialize JSON bytes to an object."""
        json_data = json.loads(data.decode('utf-8'))
        return json_data
    
    def _convert_to_serializable(self, obj: Any) -> Any:
        """Convert objects to JSON-serializable format."""
        if isinstance(obj, Node):
            return {
                'type': 'Node',
                'id': obj.id,
                'labels': list(obj.labels),
                'properties': obj.properties
            }
        elif isinstance(obj, Edge):
            return {
                'type': 'Edge',
                'id': obj.id,
                'source_id': obj.source_id,
                'target_id': obj.target_id,
                'relationship_type': obj.relationship_type,
                'properties': obj.properties
            }
        elif isinstance(obj, Graph):
            return {
                'type': 'Graph',
                'nodes': [self._convert_to_serializable(node) for node in obj._nodes.values()],
                'edges': [self._convert_to_serializable(edge) for edge in obj._edges.values()]
            }
        elif isinstance(obj, list):
            return [self._convert_to_serializable(item) for item in obj]
        elif isinstance(obj, dict):
            return {key: self._convert_to_serializable(value) for key, value in obj.items()}
        else:
            return obj


class BinaryFormat:
    """Binary serialization format using pickle."""
    
    def serialize(self, obj: Any) -> bytes:
        """Serialize an object to binary bytes using pickle."""
        return pickle.dumps(obj)
    
    def deserialize(self, data: bytes) -> Any:
        """Deserialize binary bytes to an object using pickle."""
        return pickle.loads(data)


class Serializer:
    """Main serializer class that supports multiple formats."""
    
    def __init__(self, format_impl: SerializationFormat = None):
        self.format = format_impl or JSONFormat()
    
    def serialize_node(self, node: Node) -> bytes:
        """Serialize a node."""
        return self.format.serialize(node)
    
    def serialize_edge(self, edge: Edge) -> bytes:
        """Serialize an edge."""
        return self.format.serialize(edge)
    
    def serialize_graph(self, graph: Graph) -> bytes:
        """Serialize an entire graph."""
        return self.format.serialize(graph)
    
    def serialize_nodes(self, nodes: List[Node]) -> bytes:
        """Serialize a list of nodes."""
        return self.format.serialize(nodes)
    
    def serialize_edges(self, edges: List[Edge]) -> bytes:
        """Serialize a list of edges."""
        return self.format.serialize(edges)
    
    def deserialize(self, data: bytes) -> Any:
        """Deserialize data back to objects."""
        return self.format.deserialize(data)
    
    def deserialize_to_graph(self, data: bytes) -> Graph:
        """Deserialize data to a Graph object."""
        obj = self.deserialize(data)
        
        if isinstance(obj, dict) and obj.get('type') == 'Graph':
            graph = Graph()
            
            # Recreate nodes
            for node_data in obj.get('nodes', []):
                node = Node(
                    id=node_data['id'],
                    labels=set(node_data['labels']),
                    properties=node_data['properties']
                )
                graph.add_node(node)
            
            # Recreate edges
            for edge_data in obj.get('edges', []):
                edge = Edge(
                    id=edge_data['id'],
                    source_id=edge_data['source_id'],
                    target_id=edge_data['target_id'],
                    relationship_type=edge_data['relationship_type'],
                    properties=edge_data['properties']
                )
                graph.add_edge(edge)
            
            return graph
        
        raise ValueError("Data does not represent a valid graph")
    
    def save_to_file(self, obj: Any, filename: str) -> None:
        """Save an object to a file."""
        data = self.format.serialize(obj)
        with open(filename, 'wb') as f:
            f.write(data)
    
    def load_from_file(self, filename: str) -> Any:
        """Load an object from a file."""
        with open(filename, 'rb') as f:
            data = f.read()
        return self.format.deserialize(data)
    
    def load_graph_from_file(self, filename: str) -> Graph:
        """Load a graph from a file."""
        with open(filename, 'rb') as f:
            data = f.read()
        return self.deserialize_to_graph(data)