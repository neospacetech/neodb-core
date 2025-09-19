"""Tests for serialization functionality."""

import json
import tempfile
import os
from neodb.core.graph import Graph, Node, Edge
from neodb.serialization.serializer import Serializer, JSONFormat, BinaryFormat
from neodb.serialization.formats import CompressedJSONFormat


class TestJSONFormat:
    """Test JSON serialization format."""
    
    def test_serialize_node(self):
        """Test serializing a node to JSON."""
        format_impl = JSONFormat()
        
        node = Node(id="test", labels={"Person"}, properties={"name": "John", "age": 30})
        serialized = format_impl.serialize(node)
        
        assert isinstance(serialized, bytes)
        
        # Deserialize and check content
        data = json.loads(serialized.decode('utf-8'))
        assert data["type"] == "Node"
        assert data["id"] == "test"
        assert "Person" in data["labels"]
        assert data["properties"]["name"] == "John"
        assert data["properties"]["age"] == 30
    
    def test_serialize_edge(self):
        """Test serializing an edge to JSON."""
        format_impl = JSONFormat()
        
        edge = Edge(id="test", source_id="1", target_id="2", 
                   relationship_type="KNOWS", properties={"since": 2020})
        serialized = format_impl.serialize(edge)
        
        data = json.loads(serialized.decode('utf-8'))
        assert data["type"] == "Edge" 
        assert data["source_id"] == "1"
        assert data["target_id"] == "2"
        assert data["relationship_type"] == "KNOWS"
        assert data["properties"]["since"] == 2020
    
    def test_serialize_graph(self):
        """Test serializing a complete graph."""
        format_impl = JSONFormat()
        
        graph = Graph()
        node1 = Node(id="1", labels={"Person"})
        node2 = Node(id="2", labels={"Person"})
        edge = Edge(source_id="1", target_id="2", relationship_type="KNOWS")
        
        graph.add_node(node1)
        graph.add_node(node2)
        graph.add_edge(edge)
        
        serialized = format_impl.serialize(graph)
        data = json.loads(serialized.decode('utf-8'))
        
        assert data["type"] == "Graph"
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1
    
    def test_deserialize_json(self):
        """Test deserializing JSON data."""
        format_impl = JSONFormat()
        
        json_data = {
            "type": "Node",
            "id": "test",
            "labels": ["Person"],
            "properties": {"name": "John"}
        }
        
        serialized = json.dumps(json_data).encode('utf-8')
        deserialized = format_impl.deserialize(serialized)
        
        assert deserialized == json_data


class TestBinaryFormat:
    """Test binary serialization format."""
    
    def test_serialize_deserialize_node(self):
        """Test serializing and deserializing a node with binary format."""
        format_impl = BinaryFormat()
        
        node = Node(id="test", labels={"Person"}, properties={"name": "John"})
        serialized = format_impl.serialize(node)
        
        assert isinstance(serialized, bytes)
        
        deserialized = format_impl.deserialize(serialized)
        assert isinstance(deserialized, Node)
        assert deserialized.id == node.id
        assert deserialized.labels == node.labels
        assert deserialized.properties == node.properties


class TestSerializer:
    """Test main Serializer class."""
    
    def test_default_format(self):
        """Test serializer with default JSON format."""
        serializer = Serializer()
        
        node = Node(id="test", labels={"Person"})
        serialized = serializer.serialize_node(node)
        
        assert isinstance(serialized, bytes)
        
        # Should be JSON by default
        data = json.loads(serialized.decode('utf-8'))
        assert data["type"] == "Node"
    
    def test_custom_format(self):
        """Test serializer with custom format."""
        serializer = Serializer(BinaryFormat())
        
        node = Node(id="test", labels={"Person"})
        serialized = serializer.serialize_node(node)
        
        # Should be binary format
        deserialized = serializer.deserialize(serialized)
        assert isinstance(deserialized, Node)
        assert deserialized.id == "test"
    
    def test_serialize_nodes_list(self):
        """Test serializing a list of nodes."""
        serializer = Serializer()
        
        nodes = [
            Node(id="1", labels={"Person"}),
            Node(id="2", labels={"Company"})
        ]
        
        serialized = serializer.serialize_nodes(nodes)
        data = json.loads(serialized.decode('utf-8'))
        
        assert isinstance(data, list)
        assert len(data) == 2
    
    def test_serialize_edges_list(self):
        """Test serializing a list of edges."""
        serializer = Serializer()
        
        edges = [
            Edge(source_id="1", target_id="2", relationship_type="KNOWS"),
            Edge(source_id="2", target_id="3", relationship_type="WORKS_FOR")
        ]
        
        serialized = serializer.serialize_edges(edges)
        data = json.loads(serialized.decode('utf-8'))
        
        assert isinstance(data, list)
        assert len(data) == 2
    
    def test_serialize_graph(self):
        """Test serializing a complete graph."""
        serializer = Serializer()
        
        graph = Graph()
        node1 = Node(id="1")
        node2 = Node(id="2")
        edge = Edge(source_id="1", target_id="2", relationship_type="CONNECTED")
        
        graph.add_node(node1)
        graph.add_node(node2)
        graph.add_edge(edge)
        
        serialized = serializer.serialize_graph(graph)
        data = json.loads(serialized.decode('utf-8'))
        
        assert data["type"] == "Graph"
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1
    
    def test_deserialize_to_graph(self):
        """Test deserializing data back to a Graph object."""
        serializer = Serializer()
        
        # Create and serialize a graph
        original_graph = Graph()
        node1 = Node(id="1", labels={"Person"}, properties={"name": "John"})
        node2 = Node(id="2", labels={"Person"}, properties={"name": "Jane"})
        edge = Edge(source_id="1", target_id="2", relationship_type="KNOWS")
        
        original_graph.add_node(node1)
        original_graph.add_node(node2)
        original_graph.add_edge(edge)
        
        serialized = serializer.serialize_graph(original_graph)
        
        # Deserialize back to graph
        restored_graph = serializer.deserialize_to_graph(serialized)
        
        assert isinstance(restored_graph, Graph)
        assert restored_graph.node_count == 2
        assert restored_graph.edge_count == 1
        
        # Check nodes
        restored_node1 = restored_graph.get_node("1")
        assert restored_node1 is not None
        assert restored_node1.labels == {"Person"}
        assert restored_node1.properties["name"] == "John"
        
        # Check edges
        restored_edges = list(restored_graph._edges.values())
        assert len(restored_edges) == 1
        assert restored_edges[0].relationship_type == "KNOWS"
    
    def test_file_operations(self):
        """Test saving to and loading from files."""
        serializer = Serializer()
        
        node = Node(id="test", labels={"Person"}, properties={"name": "John"})
        
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            tmp_filename = tmp_file.name
        
        try:
            # Save to file
            serializer.save_to_file(node, tmp_filename)
            
            # Load from file
            loaded_data = serializer.load_from_file(tmp_filename)
            
            assert loaded_data["type"] == "Node"
            assert loaded_data["id"] == "test"
            assert loaded_data["properties"]["name"] == "John"
            
        finally:
            os.unlink(tmp_filename)
    
    def test_load_graph_from_file(self):
        """Test loading a graph from file."""
        serializer = Serializer()
        
        # Create a graph
        graph = Graph()
        node = Node(id="test", labels={"Person"})
        graph.add_node(node)
        
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            tmp_filename = tmp_file.name
        
        try:
            # Save graph to file
            serializer.save_to_file(graph, tmp_filename)
            
            # Load graph from file
            loaded_graph = serializer.load_graph_from_file(tmp_filename)
            
            assert isinstance(loaded_graph, Graph)
            assert loaded_graph.node_count == 1
            
            loaded_node = loaded_graph.get_node("test")
            assert loaded_node is not None
            assert loaded_node.labels == {"Person"}
            
        finally:
            os.unlink(tmp_filename)


class TestCompressedFormats:
    """Test compressed serialization formats."""
    
    def test_compressed_json_format(self):
        """Test compressed JSON format."""
        format_impl = CompressedJSONFormat()
        
        node = Node(id="test", labels={"Person"}, properties={"name": "John"})
        serialized = format_impl.serialize(node)
        
        assert isinstance(serialized, bytes)
        
        # Compressed data should be different from regular JSON
        json_format = JSONFormat()
        json_serialized = json_format.serialize(node)
        assert serialized != json_serialized
        
        # But should deserialize to the same data
        deserialized = format_impl.deserialize(serialized)
        json_deserialized = json_format.deserialize(json_serialized)
        assert deserialized == json_deserialized