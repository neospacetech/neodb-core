"""
NeoDB - A hybrid Python-Rust graph database with NeoQL query language.

This package provides the Python MVP layer for rapid prototyping of datasets,
NeoQL parsing, object serialization, and basic graph functionality.
The performance-critical core (storage engine, caching, traversal) will be
implemented in Rust for safety and efficiency.
"""

__version__ = "0.1.0"
__author__ = "NeoDB Team"
__email__ = "team@neospace.tech"

from .core.graph import Graph, Node, Edge
from .core.database import Database
from .neoql.parser import NeoQLParser
from .datasets.manager import DatasetManager

__all__ = [
    "Graph",
    "Node", 
    "Edge",
    "Database",
    "NeoQLParser",
    "DatasetManager",
]