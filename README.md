# neodb-core

NeoDB is a lightweight, embeddable, schema-aware database engine built for speed, flexibility, and developer happiness.
It introduces NeoQL, a simple, human-readable query language designed to be expressive and easy to use — both from the CLI and SDKs.

## Features
- Datasets: Create graph, table, or kvs datasets.
- NeoQL: Minimal, intuitive query language.
- In-Memory Engine: Blazing fast for prototyping and testing.
- Interactive CLI: Directly manage and query datasets.
- Composable Queries: Batch multiple operations together.

Planned Features:
- Persistence & WAL logging
- Indexing for faster queries
- Transactions with ACID guarantees
- SDK support
- Remote access (HTTP / WebSocket)

## Installation

Clone the repository and run the CLI:
```bash
git clone https://github.com/yourusername/neodb.git
cd neodb
python -m cli
```

## Example Usage
1. Create a Dataset
```
neodb> create dataset users(graph{id(int, pk), name(str(255)), age(int), score(float)})
```

2. Insert Data
```
neodb> add {id=1, name=Alice, age=25, score=4.0}, {id=2, name=Ben, age=22, score=3.5} into users
```


3. Query Data
```
neodb> users({id=1})
```

4. Batch Queries
```
neodb> begin transaction
neodb> add {id=3, name=Clara, age=28, score=4.7} into users
neodb> add {id=4, name=David, age=20, score=3.9} into users
neodb> commit
```

🧠 NeoQL at a Glance

Create Dataset:
```
create dataset <name>(<type>{<schema>})
```

Insert Objects:
```
add {field=value, ...}, {...} into <dataset>
```

Insert Into Other Objects:
```
add {field=value, ...}, {...} into <dataset>{field=value, ...}.field
```

Select Objects:
```
<dataset>({field=value, field=other_value})
```

Batch Operations:
```
begin transaction → [commands] → commit
```