"""NeoDB CLI Main Module

This module provides a command-line interface for interacting with the NeoDB engine.
"""

import json
import uuid

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

4. help
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
    return statement_to_query(parse_statement(cmd))


def print_diagnostic(error: DiagnosticError) -> None:
    """Render a public diagnostic for humans and JSON consumers."""
    print(f"Error [{error.code}]: {error}")
    print(json.dumps(error.to_dict(), sort_keys=True, default=str))


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
        transaction_id = str(uuid.uuid4())
        if isinstance(transaction_space, dict):
            if transaction_space["active"] != "":
                print("Another transaction is already active.")
                return None
            transaction_space["active"] = transaction_id
            transaction_space[transaction_id] = []
        print(f"Transaction started with ID: {transaction_id}")
        return transaction_id
    elif cmd.lower().strip() == "end transaction":
        if isinstance(transaction_space, dict):
            if transaction_space["active"] == "":
                print("No active transaction to end.")
                return None
            transaction_id = transaction_space["active"]
            transaction_space["active"] = ""
            return transaction_id
    elif cmd.lower().strip().startswith("commit"):
        if isinstance(transaction_space, dict):
            if " " in cmd:
                transaction_id = cmd.split(" ", 1)[1].strip()
            else:
                if transaction_space["active"] == "":
                    print("No active transaction to commit.")
                    return None
                transaction_id = transaction_space["active"]
                execute_cli_command(engine, "end transaction", transaction_space)
            output = run(
                engine,
                {
                    "action": "batch",
                    "queries": list(transaction_space[transaction_id]),
                },
            )
            del transaction_space[transaction_id]
            print(f"Transaction {transaction_id} committed.")
            return output
    elif cmd.lower().strip() == "abort transaction":
        if isinstance(transaction_space, dict):
            if transaction_space["active"] == "":
                print("No active transaction to abort.")
                return None
            transaction_id = transaction_space["active"]
            transaction_space["active"] = ""
            del transaction_space[transaction_id]
            print(f"Transaction {transaction_id} aborted.")
            return transaction_id

    try:
        json_query = parse_cli_command(cmd)
    except DiagnosticError as error:
        print_diagnostic(error)
        return None
    if not json_query:
        return None
    if transaction_space and transaction_space["active"] != "":
        transaction_space[transaction_space["active"]].append(json_query)
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
        return engine.execute_query(json_query)
    except DiagnosticError as error:
        print_diagnostic(error)
        return None
    except Exception as error:
        print(f"Error executing query: {error}")
        return None


def main():
    """Run the interactive NeoDB shell."""
    engine = NeoDBEngine()
    transactions = {"active": ""}
    while True:
        try:
            inp = input("neodb> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if inp.lower() in ("exit", "quit"):
            break
        print(f"Output: {execute_cli_command(engine, inp, transactions)}")


if __name__ == "__main__":
    main()
