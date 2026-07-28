"""NeoDB CLI Main Module

This module provides a command-line interface for interacting with the NeoDB engine.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from engine import NeoDBEngine
from neoql.ast import (
    AddStatement,
    CreateDatasetStatement,
    SelectionStatement,
)
from neoql.errors import DiagnosticError
from neoql.parser import (
    parse_statement,
    statement_to_query,
)
from neoql.selection import Selection

from .source import StatementBuffer, split_script

HELP_TEXT = {
    "general": """
NeoDB CLI - Available commands:

1. create dataset <name>(<type>{<schema>})
   - Create a new dataset (table or graph)
   - Example: create dataset users(table{id(int, pk), name(str(255)), age(int)})

2. add {..}, {..} into <dataset>
   - Add objects to a dataset
   - Example: add {id=1, name=Alice, age=25} into users

3. <dataset>({filters})
   - Query a dataset with optional filters
   - Example: users({age>20, score>=3.5})

4. <dataset>({filters}).update({values})
   - Update matching table records atomically
   - Example: users({id=1}).update({active=true})

5. <dataset>({filters}).delete()
   - Delete matching table records atomically
   - Example: users({inactive=true}).delete()

6. help
   - Show this help text
""",
    "create": (
        "Usage: create dataset <name>(<type>{<schema>})\n"
        "Example: create dataset users(table{id(int, pk), name(str(255))})"
    ),
    "add": (
        "Usage: add {..}, {..} into <dataset>\n"
        "Example: add {id=1, name=Alice} into users"
    ),
    "select": ("Usage: <dataset>({filters})\nExample: users({age>20})"),
    "update": (
        "Usage: <dataset>({filters}).update({values})\n"
        "Example: users({id=1}).update({active=true})"
    ),
    "delete": (
        "Usage: <dataset>({filters}).delete()\nExample: users({inactive=true}).delete()"
    ),
}


def parse_literal(value: str):
    """Parse one scalar using the NeoQL frontend."""
    return parse_object(f"{{value={value}}}")["value"]


def show_help(command=None):
    """
    Prints help text.
    If command is None, shows general help.
    """
    if command is None:
        print(HELP_TEXT["general"])
    else:
        cmd = command.lower()
        print(HELP_TEXT.get(cmd, f"No help available for '{command}'"))


def parse_schema(schema_str: str):
    """Parse a field-definition list through the NeoQL frontend."""
    query = create_dataset(f"create dataset schema(table{{{schema_str}}})")
    return query["schema"]


def parse_object(obj_str: str):
    """Parse one NeoQL record literal."""
    objects = parse_objects_list(obj_str)
    if len(objects) != 1:
        raise ValueError("Expected one record")
    return objects[0]


def parse_objects_list(objs_str: str):
    """Parse comma-separated NeoQL record literals."""
    statement = parse_statement(f"add {objs_str} into records")
    if not isinstance(statement, AddStatement):
        raise ValueError("Expected record literals")
    return statement_to_query(statement)["objects"]


def parse_filters(filter_str: str):
    """Parse a NeoQL predicate into the current engine representation."""
    if filter_str is None:
        return None
    predicate = filter_str.strip()
    if not predicate.strip("{} "):
        return None
    if not (predicate.startswith("{") and predicate.endswith("}")):
        predicate = f"{{{predicate}}}"
    statement = parse_statement(f"records({predicate})")
    if not isinstance(statement, SelectionStatement):
        raise ValueError("Expected predicate")
    return statement_to_query(statement)["filter"]


def create_dataset(cmd: str):
    """Parse a create-dataset statement."""
    statement = parse_statement(cmd)
    if not isinstance(statement, CreateDatasetStatement):
        raise ValueError("Expected create dataset statement")
    return statement_to_query(statement)


def select(cmd: str):
    """Parse a dataset selection."""
    statement = parse_statement(cmd)
    if not isinstance(statement, SelectionStatement):
        raise ValueError("Expected selection statement")
    return statement_to_query(statement)


def add(cmd: str):
    """Parse an add-records statement."""
    statement = parse_statement(cmd)
    if not isinstance(statement, AddStatement):
        raise ValueError("Expected add statement")
    return statement_to_query(statement)


def parse_cli_command(cmd: str):
    """Parse a CLI command into a structured JSON object.

    Args:
        cmd (str): The command string to parse.

    Returns:
        dict: NeoQL query.
    """
    cmd = cmd.strip()
    if cmd.lower().startswith("help"):
        show_help()
        return {}
    return compile_source(cmd)


def compile_source(source: str):
    """Compile one statement or transaction block into the engine contract."""
    stripped = source.strip()
    lowered = stripped.lower()
    if lowered.startswith("transaction"):
        prefix = stripped[: stripped.find("{")].strip().lower()
        if prefix != "transaction" or not stripped.endswith("}"):
            return statement_to_query(parse_statement(source))
        body = stripped[stripped.find("{") + 1 : -1]
        return {
            "action": "transaction",
            "queries": [
                compile_source(statement.source) for statement in split_script(body)
            ],
        }
    return statement_to_query(parse_statement(source))


def print_diagnostic(error: DiagnosticError, *, filename: str | None = None) -> None:
    """Render a public diagnostic for humans and JSON consumers."""
    prefix = ""
    if filename is not None:
        if error.span is not None:
            prefix = f"{filename}:{error.span.start.line}:{error.span.start.column}: "
        else:
            prefix = f"{filename}: "
    print(f"{prefix}Error [{error.code}]: {error}")
    payload = error.to_dict()
    if filename is not None:
        payload["filename"] = filename
    print(json.dumps(payload, sort_keys=True, default=str))


def execute_cli_command(engine: NeoDBEngine, cmd: str, transaction_space=None):
    """Execute a CLI command using the provided NeoDB engine.

    Args:
        engine (NeoDBEngine): The NeoDB engine instance.
        cmd (str): The command string to execute.
        transaction_space (optional): Transaction context, if any.

    Returns:
        list: Query results or None.
    """
    if cmd.lower().strip() in ("begin", "start transaction"):
        transaction_id = engine.begin_transaction()
        print(f"Transaction started with ID: {transaction_id}")
        return transaction_id
    if cmd.lower().strip().startswith("commit") or cmd.lower().strip() == (
        "end transaction"
    ):
        parts = cmd.split(maxsplit=1)
        requested = (
            parts[1].strip()
            if len(parts) == 2 and parts[0].lower() == "commit"
            else None
        )
        try:
            transaction_id = engine.commit_transaction(requested)
        except DiagnosticError as error:
            print_diagnostic(error)
            return None
        print(f"Transaction {transaction_id} committed.")
        return transaction_id
    if cmd.lower().strip() in {"abort", "abort transaction", "rollback"}:
        try:
            transaction_id = engine.abort_transaction()
        except DiagnosticError as error:
            print_diagnostic(error)
            return None
        print(f"Transaction {transaction_id} aborted.")
        return transaction_id

    try:
        json_query = parse_cli_command(cmd)
    except DiagnosticError as error:
        print_diagnostic(error)
        return None
    if not json_query:
        return None
    return run(engine, json_query)


def run(engine: NeoDBEngine, json_query):
    """Run a parsed NeoQL query against the NeoDB engine.

    Args:
        engine (NeoDBEngine): The NeoDB engine instance.
        json_query (dict): The parsed NeoQL query.

    Returns:
        list: Query results or None.
    """
    try:
        print("Executing query:")
        print(json.dumps(json_query, indent=2))
        result = engine.execute_query(json_query)
        return result.consume() if isinstance(result, Selection) else result
    except DiagnosticError as error:
        print_diagnostic(error)
        return None
    except Exception as error:
        print(f"Error executing query: {error}")
        return None


def run_script(path: str | Path, engine: NeoDBEngine | None = None) -> int:
    """Execute a NeoQL source file and return a deterministic exit status."""
    script_path = Path(path)
    try:
        source = script_path.read_text(encoding="utf-8")
    except OSError as error:
        print(f"{script_path}: {error}", file=sys.stderr)
        return 2

    runtime = engine or NeoDBEngine()
    for statement in split_script(source):
        located_source = "\n" * (statement.start_line - 1) + statement.source
        try:
            query = compile_source(located_source)
            result = runtime.execute_query(query)
            if isinstance(result, Selection):
                result = result.consume()
            print(json.dumps(result, sort_keys=True, default=str))
        except DiagnosticError as error:
            print_diagnostic(error, filename=str(script_path))
            return 1
    return 0


def run_repl(engine: NeoDBEngine | None = None) -> None:
    """Run the interactive shell with delimiter-aware continuation input."""
    runtime = engine or NeoDBEngine()
    transactions = {"active": ""}
    buffer = StatementBuffer()
    while True:
        try:
            inp = input("... " if buffer.pending else "neodb> ")
        except EOFError:
            print()
            for statement in buffer.finish():
                print(
                    f"Output: {execute_cli_command(runtime, statement, transactions)}"
                )
            break
        except KeyboardInterrupt:
            print()
            break
        if not buffer.pending and inp.strip().lower() in ("exit", "quit"):
            break
        for statement in buffer.feed(inp):
            print(f"Output: {execute_cli_command(runtime, statement, transactions)}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run a script or start the interactive NeoDB shell."""
    argument_parser = argparse.ArgumentParser(prog="neodb")
    argument_parser.add_argument("script", nargs="?", help="NeoQL source file")
    arguments = argument_parser.parse_args(argv)
    if arguments.script:
        return run_script(arguments.script)
    run_repl()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
