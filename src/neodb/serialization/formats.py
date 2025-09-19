"""Serialization format implementations for NeoDB.

This module provides concrete implementations of different serialization
formats that can be used with the Serializer class.
"""

import json
import pickle
import gzip
from typing import Any
from .serializer import SerializationFormat


class CompressedJSONFormat:
    """Compressed JSON serialization format."""
    
    def serialize(self, obj: Any) -> bytes:
        """Serialize an object to compressed JSON bytes."""
        json_format = JSONFormat()
        json_data = json_format.serialize(obj)
        return gzip.compress(json_data)
    
    def deserialize(self, data: bytes) -> Any:
        """Deserialize compressed JSON bytes to an object."""
        json_data = gzip.decompress(data)
        json_format = JSONFormat()
        return json_format.deserialize(json_data)


class CompressedBinaryFormat:
    """Compressed binary serialization format."""
    
    def serialize(self, obj: Any) -> bytes:
        """Serialize an object to compressed binary bytes."""
        binary_format = BinaryFormat()
        binary_data = binary_format.serialize(obj)
        return gzip.compress(binary_data)
    
    def deserialize(self, data: bytes) -> Any:
        """Deserialize compressed binary bytes to an object."""
        binary_data = gzip.decompress(data)
        binary_format = BinaryFormat()
        return binary_format.deserialize(binary_data)


# Re-export the main formats for convenience
from .serializer import JSONFormat, BinaryFormat

__all__ = [
    "JSONFormat", 
    "BinaryFormat", 
    "CompressedJSONFormat", 
    "CompressedBinaryFormat"
]