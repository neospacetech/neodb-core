# NeoDB Core

A hybrid Python-Rust graph database with NeoQL query language.

## Architecture

NeoDB follows a hybrid approach for optimal development velocity and performance:

### Phase 1: Python MVP (Current)
- **Rapid Prototyping**: Python implementation for quick iteration
- **Core Components**:
  - Graph data structures (Node, Edge, Graph)
  - NeoQL query language parser and AST
  - Object serialization system (JSON, Binary)
  - Dataset management and loading
  - Command-line interface

### Phase 2: Rust Performance Core (In Progress)
- **High Performance**: Rust implementation for production workloads
- **Core Components**:
  - Storage engine with RocksDB backend
  - In-memory caching system with LRU eviction
  - Graph traversal algorithms
  - Python FFI bindings for seamless integration

### Phase 3: Integration
- Hybrid architecture allowing gradual migration
- Python components for rapid development
- Rust components for performance-critical operations
- Unified API and seamless interoperability

## Features

### Current (Python MVP)
- ✅ Basic graph data structures and operations
- ✅ NeoQL query language parser
- ✅ JSON and binary serialization
- ✅ Dataset management and file loading
- ✅ Command-line interface
- ✅ Comprehensive test suite

### Planned (Rust Core)
- 🚧 Persistent storage with RocksDB
- 🚧 Multi-level caching system
- 🚧 High-performance graph traversal
- 🚧 Python FFI bindings
- 🚧 Concurrent access and ACID guarantees

## Quick Start

### Prerequisites
- Python 3.8+
- Rust 1.70+ (for Rust components)

### Installation

```bash
# Install Python package
pip install -e .

# For development
pip install -e ".[dev]"

# Build Rust components (optional)
cargo build --workspace
```

### Basic Usage

```python
import neodb

# Create a database
db = neodb.Database("my_graph")

# Create nodes
person = db.create_node(["Person"], {"name": "Alice", "age": 30})
company = db.create_node(["Company"], {"name": "TechCorp"})

# Create relationship
db.create_edge(person, company, "WORKS_FOR", {"since": 2020})

# Query the graph
people = db.find_nodes("Person")
print(f"Found {len(people)} people")
```

### Command Line Interface

```bash
# List datasets
neodb dataset list

# Create a new dataset
neodb dataset create my_data

# Load data from file
neodb dataset load my_data --source data.json

# Interactive query mode
neodb query my_data --interactive

# Execute specific query
neodb query my_data --query "MATCH (n:Person) RETURN n LIMIT 10"
```

### NeoQL Query Language

NeoQL is inspired by Cypher but simplified for the MVP:

```cypher
-- Match nodes with labels and properties
MATCH (n:Person {age: 30})-[r:KNOWS]->(friend:Person)
RETURN n, r, friend

-- Create new data
CREATE (p:Person {name: "Bob", age: 25})

-- Update properties
MATCH (p:Person {name: "Bob"})
SET p.age = 26

-- Delete nodes and relationships
MATCH (p:Person {name: "Bob"})
DETACH DELETE p
```

## Development

### Project Structure

```
neodb-core/
├── src/neodb/                 # Python MVP implementation
│   ├── core/                  # Graph data structures
│   ├── neoql/                 # Query language parser
│   ├── serialization/         # Object serialization
│   ├── datasets/              # Dataset management
│   └── cli.py                 # Command-line interface
├── neodb-rust/                # Rust core library
├── neodb-storage/             # Storage engine
├── neodb-cache/               # Caching system
├── neodb-traversal/           # Graph algorithms
├── neodb-ffi/                 # Python FFI bindings
└── tests/                     # Test suite
```

### Running Tests

```bash
# Python tests
pytest tests/ -v

# Rust tests  
cargo test --workspace

# With coverage
pytest tests/ --cov=neodb --cov-report=html
```

### Code Quality

```bash
# Format Python code
black src/ tests/

# Lint Python code
flake8 src/ tests/

# Type checking
mypy src/

# Format Rust code
cargo fmt --all

# Lint Rust code
cargo clippy --workspace
```

## Benchmarks

Performance benchmarks will compare:
- Python MVP vs Rust core
- Different storage backends
- Caching strategies
- Query execution performance

```bash
# Run benchmarks
cargo bench --workspace
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Submit a pull request

## Roadmap

- [x] **v0.1.0**: Python MVP with basic graph operations
- [ ] **v0.2.0**: Rust storage engine integration
- [ ] **v0.3.0**: Rust caching and performance optimizations
- [ ] **v0.4.0**: Advanced query features and optimizations
- [ ] **v1.0.0**: Production-ready hybrid architecture

## License

MIT License - see LICENSE file for details.

## Team

NeoDB is developed by the NeoDB Team at Neospace Technologies.

- **Repository**: https://github.com/neospacetech/neodb-core
- **Issues**: https://github.com/neospacetech/neodb-core/issues
- **Email**: team@neospace.tech