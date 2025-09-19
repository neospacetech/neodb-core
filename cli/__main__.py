"""NeoDB CLI Main Module

This module provides a command-line interface for interacting with the NeoDB engine.
"""

import json
import re
import uuid
from engine import NeoDBEngine

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
    "create": "Usage: create dataset <name>(<type>{<schema>})\nCreates a new dataset. Example: create dataset users(table{id(int, pk), name(str(255))})",
    "add": "Usage: add {..}, {..} into <dataset>\nAdds objects to the dataset. Example: add {id=1, name=Alice} into users",
    "select": "Usage: <dataset>({filters})\nSelects objects matching filters. Example: users({age>20})"
}


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
    """
    Parse schema like:
    id(int, pk), name(str(255)), age(int)
    Keeps type with inner parentheses (str(255)), constraints only if extra.
    """
    schema = {}
    
    parts = []
    bracket_level = 0
    current = ""
    for c in schema_str:
        if c == "(":
            bracket_level += 1
        elif c == ")":
            bracket_level -= 1
        if c == "," and bracket_level == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += c
    if current:
        parts.append(current.strip())

    for field_def in parts:
        if "(" not in field_def or not field_def.endswith(")"):
            continue
        field_name = field_def[:field_def.index("(")].strip()
        props_str = field_def[field_def.index("(")+1:-1].strip()

        props = []
        current_prop = ""
        nested = 0
        for ch in props_str:
            if ch == "(":
                nested += 1
            elif ch == ")":
                nested -= 1
            if ch == "," and nested == 0:
                props.append(current_prop.strip())
                current_prop = ""
            else:
                current_prop += ch
        if current_prop:
            props.append(current_prop.strip())

        # First prop is type
        schema[field_name] = {"type": props[0]}
        # Extra props are constraints
        if len(props) > 1:
            schema[field_name]["constraints"] = props[1:]

    return schema


def parse_object(obj_str: str):
    """
    Parse single object like {id=1, name=Alice, age=25}
    """
    obj = {}
    obj_str = obj_str.strip("{} ")
    for pair in obj_str.split(","):
        key, value = pair.split("=")
        key = key.strip()
        value = value.strip()
        # convert numeric values if possible
        if re.match(r"^\d+(\.\d+)?$", value):
            value = float(value) if "." in value else int(value)
        obj[key] = value
    return obj


def parse_objects_list(objs_str: str):
    """
    Parse multiple objects separated by commas
    """
    objs = []
    # Split on "}, {" while keeping braces balanced
    parts = re.findall(r"\{.*?\}", objs_str)
    for p in parts:
        objs.append(parse_object(p))
    return objs


def parse_filters(filter_str: str):
    """
    Parse filters like {age>20, score>=3.5} or {id=1}
    MVP: only AND supported
    """
    filter_str = filter_str.strip("{} ")
    conditions = []
    for cond in filter_str.split(","):
        cond = cond.strip()
        # detect operator
        op_match = re.search(r"(<=|>=|!=|=|<|>)", cond)
        if op_match:
            op = op_match.group(0)
            field, value = cond.split(op)
            field = field.strip()
            value = value.strip()
            if re.match(r"^\d+(\.\d+)?$", value):
                value = float(value) if "." in value else int(value)
            conditions.append({"field": field, "op": op, "value": value})
    return {"and": conditions} if conditions else None


def create_dataset(cmd: str):
    """
    create dataset users(graph)
    create dataset users(graph{id(int, pk), name(str(255))})
    """
    match = re.match(r"create\s+dataset\s+(\w+)\((\w+)(?:\{(.*)\})?\)",
                     cmd, re.I)
    if not match:
        raise ValueError("Invalid create dataset syntax")
    name, dtype, schema_str = match.groups()
    json_obj = {"action": "create_dataset", "name": name, "type": dtype}
    if schema_str:
        json_obj["schema"] = parse_schema(schema_str)
    return json_obj


def select(cmd: str):
    """
    users({id=1, age>20})
    """
    match = re.match(r"(\w+)\((.*)\)", cmd)
    if not match:
        raise ValueError("Invalid select syntax")
    dataset, filter_str = match.groups()
    filter_obj = parse_filters(filter_str)
    return {"action": "select", "dataset": dataset, "filter": filter_obj}


def add(cmd: str):
    """
    add {..}, {..} into users
    """
    match = re.match(r"add\s+(.*)\s+into\s+(\w+)", cmd, re.I)
    if not match:
        raise ValueError("Invalid add syntax")
    objs_str, dataset = match.groups()
    objs = parse_objects_list(objs_str)
    return {"action": "insert", "dataset": dataset, "objects": objs}


def parse_cli_command(cmd: str):
    """Parse a CLI command into a structured JSON object.

    Args:
        cmd (str): The command string to parse.

    Returns:
        dict: NeoQL query.
    """
    cmd = cmd.strip()
    if cmd.lower().startswith("create dataset"):
        return create_dataset(cmd)
    elif cmd.lower().startswith("add"):
        return add(cmd)
    elif cmd.lower().startswith("help"):
        show_help()
        return {}
    else:
        return select(cmd)


def execute_cli_command(engine: NeoDBEngine, cmd: str, transaction_space=None):
    """Execute a CLI command using the provided NeoDB engine.

    Args:
        engine (NeoDBEngine): The NeoDB engine instance.
        cmd (str): The command string to execute.
        transaction_space (optional): Transaction context, if any.

    Returns:
        list: Query results or None.
    """
    if cmd.lower().strip() == "start transaction":
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
                execute_cli_command(
                    engine, "end transaction", transaction_space
                )
            output = run(
                engine,
                {
                    "action": "batch",
                    "queries": [
                        q for q in transaction_space[transaction_id].values()
                    ],
                }
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

    json_query = parse_cli_command(cmd)
    if not json_query:
        return None
    if transaction_space["active"] != "":
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
    except Exception as e:
        print(f"Error executing query: {e}")
        return None


if __name__ == "__main__":
    engine = NeoDBEngine()
    transactions = {"active": ""}
    while True:
        inp = input("neodb> ").strip()
        if inp.lower() in ("exit", "quit"):
            break
        print(f"Output: {execute_cli_command(engine, inp, transactions)}")
