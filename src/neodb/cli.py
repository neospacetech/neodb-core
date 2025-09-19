"""Command-line interface for NeoDB.

This module provides a CLI for interacting with NeoDB databases,
executing queries, and managing datasets.
"""

import click
import json
from typing import Optional
from .core.database import Database
from .datasets.manager import DatasetManager
from .neoql.parser import NeoQLParser, ParseError


@click.group()
@click.version_option(version="0.1.0")
def main():
    """NeoDB - A hybrid Python-Rust graph database with NeoQL query language."""
    pass


@main.group()
def dataset():
    """Dataset management commands."""
    pass


@dataset.command("list")
def list_datasets():
    """List all available datasets."""
    manager = DatasetManager()
    datasets = manager.list_datasets()
    
    if not datasets:
        click.echo("No datasets found.")
        return
    
    click.echo("Available datasets:")
    for ds in datasets:
        status = "loaded" if ds["loaded"] else "stored"
        stats = ds["stats"]
        node_count = stats.get("node_count", 0)
        edge_count = stats.get("edge_count", 0)
        click.echo(f"  {ds['name']} ({status}) - {node_count} nodes, {edge_count} edges")


@dataset.command("create")
@click.argument("name")
def create_dataset(name: str):
    """Create a new dataset."""
    manager = DatasetManager()
    try:
        dataset = manager.create_dataset(name)
        click.echo(f"Created dataset: {name}")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)


@dataset.command("load")
@click.argument("name")
@click.option("--source", "-s", help="Path to source file to load data from")
def load_dataset(name: str, source: Optional[str]):
    """Load a dataset."""
    manager = DatasetManager()
    try:
        dataset = manager.load_dataset(name, source)
        stats = dataset.stats()
        click.echo(f"Loaded dataset: {name}")
        click.echo(f"  Nodes: {stats['node_count']}")
        click.echo(f"  Edges: {stats['edge_count']}")
    except Exception as e:
        click.echo(f"Error loading dataset: {e}", err=True)


@dataset.command("save")
@click.argument("name")
def save_dataset(name: str):
    """Save a dataset to storage."""
    manager = DatasetManager()
    try:
        manager.save_dataset(name)
        click.echo(f"Saved dataset: {name}")
    except Exception as e:
        click.echo(f"Error saving dataset: {e}", err=True)


@dataset.command("delete")
@click.argument("name")
@click.confirmation_option(prompt="Are you sure you want to delete this dataset?")
def delete_dataset(name: str):
    """Delete a dataset."""
    manager = DatasetManager()
    if manager.delete_dataset(name):
        click.echo(f"Deleted dataset: {name}")
    else:
        click.echo(f"Dataset not found: {name}", err=True)


@dataset.command("export")
@click.argument("name")
@click.option("--output", "-o", help="Output file path")
def export_dataset(name: str, output: Optional[str]):
    """Export a dataset to JSON."""
    manager = DatasetManager()
    try:
        data = manager.export_to_json(name)
        
        if output:
            with open(output, 'w') as f:
                json.dump(data, f, indent=2)
            click.echo(f"Exported dataset to: {output}")
        else:
            click.echo(json.dumps(data, indent=2))
    except Exception as e:
        click.echo(f"Error exporting dataset: {e}", err=True)


@main.command()
@click.argument("dataset_name")
@click.option("--query", "-q", help="NeoQL query to execute")
@click.option("--interactive", "-i", is_flag=True, help="Start interactive query mode")
def query(dataset_name: str, query: Optional[str], interactive: bool):
    """Execute NeoQL queries against a dataset."""
    manager = DatasetManager()
    
    try:
        database = manager.load_dataset(dataset_name)
        parser = NeoQLParser()
        
        if interactive:
            click.echo(f"Connected to dataset: {dataset_name}")
            click.echo("Enter NeoQL queries (type 'exit' to quit):")
            
            while True:
                try:
                    user_query = click.prompt("neodb> ", type=str)
                    if user_query.lower() in ['exit', 'quit']:
                        break
                    
                    if user_query.strip():
                        result = execute_query(database, parser, user_query)
                        display_result(result)
                        
                except KeyboardInterrupt:
                    click.echo("\nGoodbye!")
                    break
                except Exception as e:
                    click.echo(f"Error: {e}", err=True)
        
        elif query:
            result = execute_query(database, parser, query)
            display_result(result)
        
        else:
            click.echo("Please provide a query with --query or use --interactive mode")
            
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


def execute_query(database: Database, parser: NeoQLParser, query_str: str):
    """Execute a NeoQL query and return results."""
    try:
        # Parse the query
        query_ast = parser.parse(query_str)
        
        # Simple query execution (MVP implementation)
        result = {"type": "success", "data": []}
        
        for clause in query_ast.clauses:
            if hasattr(clause, '__class__'):
                clause_type = clause.__class__.__name__
                if clause_type == "MatchClause":
                    # Simple MATCH implementation
                    if hasattr(clause, 'patterns'):
                        for pattern in clause.patterns:
                            # For now, just return some nodes
                            nodes = list(database.graph._nodes.values())[:10]  # Limit for demo
                            result["data"].extend([
                                {
                                    "id": node.id,
                                    "labels": list(node.labels),
                                    "properties": node.properties
                                } for node in nodes
                            ])
                
                elif clause_type == "ReturnClause":
                    # Return clause processed - results prepared above
                    pass
                
                elif clause_type == "CreateClause":
                    # Simple CREATE implementation
                    node = database.create_node(["TestNode"], {"created_by": "cli"})
                    result["data"].append({
                        "created": True,
                        "node_id": node.id
                    })
        
        return result
        
    except ParseError as e:
        return {"type": "error", "message": f"Parse error: {e}"}
    except Exception as e:
        return {"type": "error", "message": f"Execution error: {e}"}


def display_result(result):
    """Display query results."""
    if result["type"] == "error":
        click.echo(f"Error: {result['message']}", err=True)
        return
    
    data = result.get("data", [])
    if not data:
        click.echo("No results.")
        return
    
    click.echo(f"Results ({len(data)} items):")
    for i, item in enumerate(data):
        click.echo(f"  {i+1}: {json.dumps(item, indent=2)}")


@main.command()
def info():
    """Display NeoDB system information."""
    click.echo("NeoDB Core v0.1.0")
    click.echo("Hybrid Python-Rust Graph Database")
    click.echo("")
    click.echo("Components:")
    click.echo("  - Python MVP: Core graph operations, NeoQL parsing, serialization")
    click.echo("  - Rust Core: (Future) Performance-critical storage and traversal")
    click.echo("  - NeoQL: Query language inspired by Cypher")
    click.echo("")
    click.echo("Usage:")
    click.echo("  neodb dataset list               # List datasets")
    click.echo("  neodb dataset create mydata      # Create new dataset")
    click.echo("  neodb query mydata -i            # Interactive query mode")
    click.echo("  neodb query mydata -q 'MATCH (n) RETURN n'  # Execute query")


if __name__ == "__main__":
    main()