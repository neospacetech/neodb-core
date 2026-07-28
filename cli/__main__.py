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


def split_top_level(value: str, delimiter: str = ","):
    """Split text on a delimiter, ignoring quoted and nested occurrences."""
    parts = []
    current = []
    depth = 0
    quote = None
    escaped = False
    for char in value:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\" and quote:
            current.append(char)
            escaped = True
            continue
        if char in ('"', "'"):
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
            current.append(char)
            continue
        if quote is None:
            if char in "({[":
                depth += 1
            elif char in ")}]":
                depth -= 1
            if char == delimiter and depth == 0:
                parts.append("".join(current).strip())
                current = []
                continue
        current.append(char)
    if current:
        parts.append("".join(current).strip())
    return parts


def parse_literal(value: str):
    """Parse a NeoQL scalar literal into its Python representation."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return bytes(value[1:-1], "utf-8").decode("unicode_escape")
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?(?:\d+\.\d*|\d*\.\d+)", value):
        return float(value)
    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if lowered in ("null", "none"):
        return None
    return value


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

    parts = split_top_level(schema_str)

    for field_def in parts:
        if "(" not in field_def or not field_def.endswith(")"):
            continue
        field_name = field_def[: field_def.index("(")].strip()
        props_str = field_def[field_def.index("(") + 1 : -1].strip()

        props = split_top_level(props_str)

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
    for pair in split_top_level(obj_str):
        key, separator, value = pair.partition("=")
        if not separator:
            raise ValueError(f"Invalid record field: {pair}")
        key = key.strip()
        obj[key] = parse_literal(value)
    return obj


def parse_objects_list(objs_str: str):
    """
    Parse multiple objects separated by commas
    """
    objs = []
    for part in split_top_level(objs_str):
        if not (part.startswith("{") and part.endswith("}")):
            raise ValueError(f"Invalid record: {part}")
        objs.append(parse_object(part))
    return objs


def parse_filters(filter_str: str):
    """
    Parse filters like {age>20, score>=3.5} or {id=1}
    Supports &&, ||, comparison operators, and common string operators.
    """
    if filter_str is None:
        return None
    filter_str = filter_str.strip("{} ")
    if not filter_str:
        return None
    or_parts = re.split(r"\s*\|\|\s*", filter_str)
    if len(or_parts) > 1:
        return {"or": [parse_filters(part) for part in or_parts]}
    and_parts = re.split(r"\s*(?:&&|,)\s*", filter_str)
    if len(and_parts) > 1:
        return {"and": [parse_filters(part) for part in and_parts]}
    if filter_str.startswith("!"):
        return {"not": parse_filters(filter_str[1:].strip())}

    conditions = []
    for cond in [filter_str]:
        cond = cond.strip()
        op_match = re.search(
            r"\s+(startsWith|endsWith|contains|matches|in)\s+|"
            r"(<=|>=|!=|=|<|>)",
            cond,
        )
        if op_match:
            op = (op_match.group(1) or op_match.group(2)).strip()
            field = cond[: op_match.start()].strip()
            value = cond[op_match.end() :].strip()
            field = field.strip()
            conditions.append({"field": field, "op": op, "value": parse_literal(value)})
    if not conditions:
        raise ValueError(f"Invalid predicate: {filter_str}")
    return conditions[0]


def create_dataset(cmd: str):
    """
    create dataset users(graph)
    create dataset users(graph{id(int, pk), name(str(255))})
    """
    match = re.match(r"create\s+dataset\s+(\w+)\((\w+)(?:\{(.*)\})?\)", cmd, re.I)
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
    match = re.fullmatch(r"(\w+)\((\{.*\})?\)(.*)", cmd.strip(), re.S)
    if not match:
        raise ValueError("Invalid select syntax")
    dataset, filter_str, methods = match.groups()
    filter_obj = parse_filters(filter_str)
    query = {"action": "select", "dataset": dataset, "filter": filter_obj}
    while methods:
        method = re.match(r"^\s*\.\s*(\w*)\(([^()]*)\)(.*)$", methods, re.S)
        if not method:
            raise ValueError(f"Invalid selection method chain: {methods}")
        name, args, methods = method.groups()
        args = args.strip()
        if name == "":
            query["select"] = [
                field.strip() for field in args.split(",") if field.strip()
            ]
        elif name == "order":
            order = args.rsplit(maxsplit=1)
            direction = order[1].lower() if len(order) == 2 else "asc"
            if direction not in ("asc", "desc"):
                order, direction = [args], "asc"
            query.setdefault("order_by", []).append(
                {"field": order[0], "direction": direction}
            )
        elif name in ("limit", "offset"):
            query[name] = int(args)
        else:
            raise ValueError(f"Unsupported selection method '{name}'")
    return query


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

    json_query = parse_cli_command(cmd)
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
    except Exception as e:
        print(f"Error executing query: {e}")
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
