"""Registry and deterministic runtime contract for NeoQL scalar built-ins."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from .errors import FunctionArityError, FunctionTypeError

BuiltinImplementation = Callable[[list[Any], "BuiltinContext"], Any]


@dataclass(frozen=True, slots=True)
class BuiltinContext:
    """Injectable nondeterministic providers used by temporal/identity calls."""

    clock: Callable[[], datetime]
    uuid_source: Callable[[], UUID]


@dataclass(frozen=True, slots=True)
class BuiltinFunction:
    """One named built-in with a stable arity and implementation."""

    name: str
    minimum_arity: int
    maximum_arity: int
    implementation: BuiltinImplementation

    def call(self, arguments: list[Any], context: BuiltinContext) -> Any:
        actual = len(arguments)
        if not self.minimum_arity <= actual <= self.maximum_arity:
            expected: int | str
            if self.minimum_arity == self.maximum_arity:
                expected = self.minimum_arity
            else:
                expected = f"{self.minimum_arity} or {self.maximum_arity}"
            raise FunctionArityError(self.name, expected, actual)
        return self.implementation(arguments, context)


def default_builtin_context() -> BuiltinContext:
    return BuiltinContext(lambda: datetime.now(timezone.utc), uuid4)


def call_builtin(
    name: str,
    arguments: list[Any],
    context: BuiltinContext,
) -> Any:
    function = BUILTINS.get(name.lower())
    if function is None:
        raise KeyError(name)
    return function.call(arguments, context)


def _nullable_unary(
    name: str,
    arguments: list[Any],
    accepted: str,
    predicate: Callable[[Any], bool],
    operation: Callable[[Any], Any],
) -> Any:
    value = arguments[0]
    if value is None:
        return None
    if not predicate(value):
        raise FunctionTypeError(name, 1, accepted, value)
    return operation(value)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def _len(arguments: list[Any], _context: BuiltinContext) -> Any:
    return _nullable_unary(
        "len",
        arguments,
        "str, bytes, list, set, tuple, or map",
        lambda value: isinstance(
            value,
            (str, bytes, list, tuple, set, frozenset, Mapping),
        ),
        len,
    )


def _abs(arguments: list[Any], _context: BuiltinContext) -> Any:
    return _nullable_unary("abs", arguments, "number", _is_number, abs)


def _round(arguments: list[Any], _context: BuiltinContext) -> Any:
    value = arguments[0]
    digits = arguments[1] if len(arguments) == 2 else None
    if value is None or (len(arguments) == 2 and digits is None):
        return None
    if not _is_number(value):
        raise FunctionTypeError("round", 1, "number", value)
    if len(arguments) == 2 and (
        not isinstance(digits, int) or isinstance(digits, bool)
    ):
        raise FunctionTypeError("round", 2, "int", digits)
    return round(value) if len(arguments) == 1 else round(value, digits)


def _text(
    name: str,
    arguments: list[Any],
    operation: Callable[[str], str],
) -> Any:
    return _nullable_unary(
        name,
        arguments,
        "str",
        lambda value: isinstance(value, str),
        operation,
    )


def _contains(arguments: list[Any], _context: BuiltinContext) -> Any:
    container, member = arguments
    if container is None or member is None:
        return None
    if isinstance(container, str):
        if not isinstance(member, str):
            raise FunctionTypeError("contains", 2, "str", member)
        return member in container
    if isinstance(container, (bytes, Collection, Mapping)):
        try:
            return member in container
        except TypeError as error:
            raise FunctionTypeError(
                "contains",
                2,
                "a value compatible with the container",
                member,
            ) from error
    raise FunctionTypeError(
        "contains",
        1,
        "str, bytes, list, set, tuple, or map",
        container,
    )


def _today(_arguments: list[Any], context: BuiltinContext) -> date:
    return context.clock().date()


def _now(_arguments: list[Any], context: BuiltinContext) -> datetime:
    return context.clock()


def _uuid(_arguments: list[Any], context: BuiltinContext) -> UUID:
    return context.uuid_source()


BUILTINS: Mapping[str, BuiltinFunction] = {
    function.name: function
    for function in (
        BuiltinFunction("len", 1, 1, _len),
        BuiltinFunction("abs", 1, 1, _abs),
        BuiltinFunction("round", 1, 2, _round),
        BuiltinFunction(
            "lower", 1, 1, lambda args, ctx: _text("lower", args, str.lower)
        ),
        BuiltinFunction(
            "upper", 1, 1, lambda args, ctx: _text("upper", args, str.upper)
        ),
        BuiltinFunction("contains", 2, 2, _contains),
        BuiltinFunction("today", 0, 0, _today),
        BuiltinFunction("now", 0, 0, _now),
        BuiltinFunction("uuid", 0, 0, _uuid),
    )
}
BUILTIN_NAMES = frozenset(BUILTINS)
