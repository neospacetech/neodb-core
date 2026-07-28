"""Semantic types, inference, casting, and serialization for NeoQL."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, TypeAlias
from uuid import UUID

from .ast import CreateDatasetStatement, Literal, TypeRef
from .errors import DiagnosticError
from .parser import parse_statement


class NeoQLTypeError(DiagnosticError):
    """Raised when a NeoQL type or cast is invalid."""

    def __init__(self, message: str, *, code: str = "type_mismatch"):
        super().__init__(
            code,
            message,
            category="type",
            phase="compile",
        )


class TypeKind(str, Enum):
    INT = "int"
    FLOAT = "float"
    DECIMAL = "decimal"
    BOOL = "bool"
    CHAR = "char"
    STR = "str"
    TEXT = "text"
    DATE = "date"
    TIME = "time"
    DATETIME = "datetime"
    TIMESTAMP = "timestamp"
    DURATION = "duration"
    UUID = "uuid"
    BYTES = "bytes"
    JSON = "json"
    LIST = "list"
    SET = "set"
    MAP = "map"
    TUPLE = "tuple"
    REFERENCE = "reference"
    NULLABLE = "nullable"
    ENUM = "enum"


ScalarArgument: TypeAlias = str | int | float | bool | None
TypeArgument: TypeAlias = "TypeDescriptor | ScalarArgument"

PRIMITIVE_KINDS = frozenset(
    {
        TypeKind.INT,
        TypeKind.FLOAT,
        TypeKind.DECIMAL,
        TypeKind.BOOL,
        TypeKind.CHAR,
        TypeKind.STR,
        TypeKind.TEXT,
        TypeKind.DATE,
        TypeKind.TIME,
        TypeKind.DATETIME,
        TypeKind.TIMESTAMP,
        TypeKind.DURATION,
        TypeKind.UUID,
        TypeKind.BYTES,
        TypeKind.JSON,
    }
)


@dataclass(frozen=True, slots=True)
class TypeDescriptor:
    """An immutable, validated NeoQL type."""

    kind: TypeKind
    arguments: tuple[TypeArgument, ...] = ()

    def __post_init__(self) -> None:
        self._validate()

    @property
    def is_nullable(self) -> bool:
        return self.kind == TypeKind.NULLABLE

    def display(self) -> str:
        if self.kind == TypeKind.REFERENCE:
            return str(self.arguments[0])
        if not self.arguments:
            return self.kind.value
        rendered = ", ".join(_display_argument(arg) for arg in self.arguments)
        return f"{self.kind.value}({rendered})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "arguments": [
                argument.to_dict() if isinstance(argument, TypeDescriptor) else argument
                for argument in self.arguments
            ],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TypeDescriptor":
        try:
            kind = TypeKind(payload["kind"])
            raw_arguments = payload.get("arguments", [])
        except (KeyError, TypeError, ValueError) as error:
            raise NeoQLTypeError("Invalid serialized type descriptor") from error
        if not isinstance(raw_arguments, list):
            raise NeoQLTypeError("Serialized type arguments must be a list")
        arguments: list[TypeArgument] = []
        for argument in raw_arguments:
            if isinstance(argument, Mapping):
                arguments.append(cls.from_dict(argument))
            elif argument is None or isinstance(argument, (str, int, float, bool)):
                arguments.append(argument)
            else:
                raise NeoQLTypeError("Invalid serialized type argument")
        return cls(kind, tuple(arguments))

    def _validate(self) -> None:
        if self.kind in PRIMITIVE_KINDS:
            if self.kind == TypeKind.STR:
                if (
                    len(self.arguments) != 1
                    or not isinstance(self.arguments[0], int)
                    or isinstance(self.arguments[0], bool)
                    or self.arguments[0] <= 0
                ):
                    raise NeoQLTypeError("str requires one positive integer length")
            elif self.arguments:
                raise NeoQLTypeError(
                    f"{self.kind.value} does not accept type arguments"
                )
            return
        if self.kind in {TypeKind.LIST, TypeKind.SET, TypeKind.NULLABLE}:
            _require_type_arguments(self.kind, self.arguments, exactly=1)
            wrapped = self.arguments[0]
            assert isinstance(wrapped, TypeDescriptor)
            if self.kind == TypeKind.NULLABLE and wrapped.kind == TypeKind.NULLABLE:
                raise NeoQLTypeError("nullable cannot directly wrap nullable")
            return
        if self.kind == TypeKind.MAP:
            _require_type_arguments(self.kind, self.arguments, exactly=2)
            return
        if self.kind == TypeKind.TUPLE:
            _require_type_arguments(self.kind, self.arguments, minimum=1)
            return
        if self.kind == TypeKind.REFERENCE:
            if (
                len(self.arguments) != 1
                or not isinstance(self.arguments[0], str)
                or not self.arguments[0]
            ):
                raise NeoQLTypeError("reference requires one dataset name")
            return
        if self.kind == TypeKind.ENUM:
            if not self.arguments:
                raise NeoQLTypeError("enum requires at least one value")
            if any(
                isinstance(argument, TypeDescriptor)
                or not (
                    argument is None or isinstance(argument, (str, int, float, bool))
                )
                for argument in self.arguments
            ):
                raise NeoQLTypeError("enum arguments must be scalar literals")
            if len(set(self.arguments)) != len(self.arguments):
                raise NeoQLTypeError("enum values must be unique")


def _require_type_arguments(
    kind: TypeKind,
    arguments: tuple[TypeArgument, ...],
    *,
    exactly: int | None = None,
    minimum: int | None = None,
) -> None:
    if exactly is not None and len(arguments) != exactly:
        raise NeoQLTypeError(
            f"{kind.value} requires exactly {exactly} type argument(s)"
        )
    if minimum is not None and len(arguments) < minimum:
        raise NeoQLTypeError(
            f"{kind.value} requires at least {minimum} type argument(s)"
        )
    if not all(isinstance(argument, TypeDescriptor) for argument in arguments):
        raise NeoQLTypeError(f"{kind.value} arguments must be types")


def _display_argument(argument: TypeArgument) -> str:
    if isinstance(argument, TypeDescriptor):
        return argument.display()
    if isinstance(argument, str):
        return json.dumps(argument)
    if argument is True:
        return "true"
    if argument is False:
        return "false"
    if argument is None:
        return "null"
    return str(argument)


def resolve_type(type_ref: TypeRef) -> TypeDescriptor:
    """Validate and resolve a parsed type reference."""
    name = type_ref.name.lower()
    try:
        kind = TypeKind(name)
    except ValueError:
        if type_ref.arguments:
            raise NeoQLTypeError(
                f"Reference type '{type_ref.name}' cannot have arguments"
            ) from None
        return TypeDescriptor(TypeKind.REFERENCE, (type_ref.name,))

    if kind == TypeKind.REFERENCE:
        raise NeoQLTypeError("Use a dataset name to declare a reference")

    arguments: list[TypeArgument] = []
    for argument in type_ref.arguments:
        if isinstance(argument, TypeRef):
            if kind == TypeKind.ENUM and not argument.arguments:
                arguments.append(argument.name)
            else:
                arguments.append(resolve_type(argument))
        elif isinstance(argument, Literal):
            arguments.append(argument.value)
    return TypeDescriptor(kind, tuple(arguments))


def parse_type(source: str) -> TypeDescriptor:
    """Parse and validate a standalone NeoQL type expression."""
    statement = parse_statement(f"create dataset __type__(table{{value({source})}})")
    if not isinstance(statement, CreateDatasetStatement):
        raise NeoQLTypeError("Expected a type expression")
    return resolve_type(statement.fields[0].type_ref)


def infer_type(value: Any) -> TypeDescriptor:
    """Infer a NeoQL type from a Python literal value."""
    if value is None:
        raise NeoQLTypeError("Cannot infer a type from null without context")
    if isinstance(value, bool):
        return TypeDescriptor(TypeKind.BOOL)
    if isinstance(value, int):
        return TypeDescriptor(TypeKind.INT)
    if isinstance(value, float):
        return TypeDescriptor(TypeKind.FLOAT)
    if isinstance(value, Decimal):
        return TypeDescriptor(TypeKind.DECIMAL)
    if isinstance(value, str):
        if len(value) == 1:
            return TypeDescriptor(TypeKind.CHAR)
        return TypeDescriptor(TypeKind.STR, (max(1, len(value)),))
    if isinstance(value, datetime):
        return TypeDescriptor(TypeKind.DATETIME)
    if isinstance(value, date):
        return TypeDescriptor(TypeKind.DATE)
    if isinstance(value, time):
        return TypeDescriptor(TypeKind.TIME)
    if isinstance(value, timedelta):
        return TypeDescriptor(TypeKind.DURATION)
    if isinstance(value, UUID):
        return TypeDescriptor(TypeKind.UUID)
    if isinstance(value, bytes):
        return TypeDescriptor(TypeKind.BYTES)
    if isinstance(value, list):
        return TypeDescriptor(TypeKind.LIST, (_infer_collection_member(value),))
    if isinstance(value, set):
        return TypeDescriptor(TypeKind.SET, (_infer_collection_member(value),))
    if isinstance(value, tuple):
        if not value:
            raise NeoQLTypeError("Cannot infer an empty tuple type")
        return TypeDescriptor(TypeKind.TUPLE, tuple(infer_type(item) for item in value))
    if isinstance(value, dict):
        if not value:
            raise NeoQLTypeError("Cannot infer an empty map type")
        return TypeDescriptor(
            TypeKind.MAP,
            (
                _infer_collection_member(value.keys()),
                _infer_collection_member(value.values()),
            ),
        )
    raise NeoQLTypeError(f"Cannot infer a NeoQL type from {type(value).__name__}")


def _infer_collection_member(values: Any) -> TypeDescriptor:
    iterator = iter(values)
    try:
        first = next(iterator)
    except StopIteration as error:
        raise NeoQLTypeError("Cannot infer an empty collection type") from error
    inferred = infer_type(first)
    if any(infer_type(value) != inferred for value in iterator):
        raise NeoQLTypeError("Collection literals must have one element type")
    return inferred


def cast_value(value: Any, target: TypeDescriptor) -> Any:
    """Cast a Python value to a validated NeoQL type."""
    if target.kind == TypeKind.NULLABLE:
        if value is None:
            return None
        return cast_value(value, _type_argument(target, 0))
    if value is None:
        raise NeoQLTypeError(f"Cannot cast null to {target.display()}")
    try:
        if target.kind == TypeKind.INT:
            if isinstance(value, bool):
                raise ValueError
            return int(value)
        if target.kind == TypeKind.FLOAT:
            return float(value)
        if target.kind == TypeKind.DECIMAL:
            return Decimal(str(value))
        if target.kind == TypeKind.BOOL:
            return _cast_bool(value)
        if target.kind == TypeKind.CHAR:
            rendered = str(value)
            if len(rendered) != 1:
                raise ValueError
            return rendered
        if target.kind == TypeKind.STR:
            rendered = str(value)
            length = target.arguments[0]
            assert isinstance(length, int)
            if len(rendered) > length:
                raise NeoQLTypeError(f"Value exceeds {target.display()} maximum length")
            return rendered
        if target.kind == TypeKind.TEXT:
            return str(value)
        if target.kind == TypeKind.DATE:
            return value if isinstance(value, date) else date.fromisoformat(str(value))
        if target.kind == TypeKind.TIME:
            return value if isinstance(value, time) else time.fromisoformat(str(value))
        if target.kind == TypeKind.DATETIME:
            return (
                value
                if isinstance(value, datetime)
                else datetime.fromisoformat(str(value))
            )
        if target.kind == TypeKind.TIMESTAMP:
            if isinstance(value, datetime):
                return value
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        if target.kind == TypeKind.DURATION:
            return (
                value
                if isinstance(value, timedelta)
                else timedelta(seconds=float(value))
            )
        if target.kind == TypeKind.UUID:
            return value if isinstance(value, UUID) else UUID(str(value))
        if target.kind == TypeKind.BYTES:
            return value if isinstance(value, bytes) else str(value).encode()
        if target.kind == TypeKind.JSON:
            json.dumps(value)
            return value
        if target.kind == TypeKind.LIST:
            return [cast_value(item, _type_argument(target, 0)) for item in value]
        if target.kind == TypeKind.SET:
            return {cast_value(item, _type_argument(target, 0)) for item in value}
        if target.kind == TypeKind.MAP:
            key_type = _type_argument(target, 0)
            value_type = _type_argument(target, 1)
            return {
                cast_value(key, key_type): cast_value(item, value_type)
                for key, item in value.items()
            }
        if target.kind == TypeKind.TUPLE:
            if len(value) != len(target.arguments):
                raise NeoQLTypeError("Tuple value has the wrong length")
            return tuple(
                cast_value(item, _type_argument(target, index))
                for index, item in enumerate(value)
            )
        if target.kind == TypeKind.ENUM:
            if value not in target.arguments:
                raise NeoQLTypeError(f"{value!r} is not a member of {target.display()}")
            return value
        if target.kind == TypeKind.REFERENCE:
            raise NeoQLTypeError("Reference casting requires a dataset resolver")
    except (TypeError, ValueError, OverflowError) as error:
        raise NeoQLTypeError(f"Cannot cast {value!r} to {target.display()}") from error
    raise NeoQLTypeError(f"Unsupported target type {target.display()}")


def _type_argument(target: TypeDescriptor, index: int) -> TypeDescriptor:
    argument = target.arguments[index]
    assert isinstance(argument, TypeDescriptor)
    return argument


def _cast_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise ValueError
