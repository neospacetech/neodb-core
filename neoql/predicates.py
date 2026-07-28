"""Typed predicate validation and evaluation."""

import re
from collections.abc import Mapping, Sequence, Set
from decimal import Decimal
from typing import Any

from .errors import DiagnosticError
from .schema import DatasetSchema
from .types import (
    NeoQLTypeError,
    TypeDescriptor,
    TypeKind,
    infer_type,
)

COMPARISON_OPERATORS = frozenset({"=", "!=", ">", ">=", "<", "<="})
MEMBERSHIP_OPERATORS = frozenset({"in", "contains"})
STRING_OPERATORS = frozenset({"startsWith", "endsWith", "matches"})
PREDICATE_OPERATORS = COMPARISON_OPERATORS | MEMBERSHIP_OPERATORS | STRING_OPERATORS
_MISSING = object()
_NUMERIC_TYPES = (int, float, Decimal)
_STRING_TYPE_KINDS = frozenset({TypeKind.CHAR, TypeKind.STR, TypeKind.TEXT})
_ORDERABLE_TYPE_KINDS = frozenset(
    {
        TypeKind.INT,
        TypeKind.FLOAT,
        TypeKind.DECIMAL,
        TypeKind.CHAR,
        TypeKind.STR,
        TypeKind.TEXT,
        TypeKind.DATE,
        TypeKind.TIME,
        TypeKind.DATETIME,
        TypeKind.TIMESTAMP,
        TypeKind.DURATION,
    }
)


class PredicateEvaluationError(DiagnosticError):
    """A structured predicate validation or evaluation failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        field: str | None = None,
        operator: str | None = None,
        expected: str | None = None,
        actual: str | None = None,
    ):
        self.code = code
        self.field = field
        self.operator = operator
        self.expected = expected
        self.actual = actual
        details = {
            key: value
            for key, value in {
                "field": field,
                "operator": operator,
                "expected": expected,
                "actual": actual,
            }.items()
            if value is not None
        }
        super().__init__(
            code,
            message,
            category="predicate",
            phase="plan",
            details=details,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload.update(
            {
                "field": self.field,
                "operator": self.operator,
                "expected": self.expected,
                "actual": self.actual,
            }
        )
        return payload


def evaluate_predicate(
    record: Mapping[str, Any], predicate: Mapping[str, Any] | None
) -> bool:
    """Evaluate a compiled predicate against one record."""
    if not predicate:
        return True
    if "and" in predicate:
        operands = _logical_operands(predicate, "and")
        return all(evaluate_predicate(record, item) for item in operands)
    if "or" in predicate:
        operands = _logical_operands(predicate, "or")
        return any(evaluate_predicate(record, item) for item in operands)
    if "not" in predicate:
        operand = predicate["not"]
        if not isinstance(operand, Mapping):
            raise PredicateEvaluationError(
                "invalid_predicate", "not requires one predicate"
            )
        return not evaluate_predicate(record, operand)

    field, operator, expected = _comparison_parts(predicate)
    actual = record.get(field, _MISSING)
    if actual is _MISSING:
        raise PredicateEvaluationError(
            "missing_field",
            f"Predicate field '{field}' is missing",
            field=field,
            operator=operator,
        )
    return evaluate_operator(actual, operator, expected, field=field)


def evaluate_operator(
    actual: Any,
    operator: str,
    expected: Any,
    *,
    field: str | None = None,
) -> bool:
    """Evaluate one typed predicate operation."""
    if operator not in PREDICATE_OPERATORS:
        raise PredicateEvaluationError(
            "unknown_operator",
            f"Unknown predicate operator '{operator}'",
            field=field,
            operator=operator,
        )
    if operator in {"=", "!="}:
        if actual is None or expected is None:
            result = actual is expected
        else:
            _ensure_compatible(actual, expected, field, operator)
            result = actual == expected
        return result if operator == "=" else not result
    if operator in {">", ">=", "<", "<="}:
        if actual is None or expected is None:
            return False
        _ensure_compatible(actual, expected, field, operator)
        try:
            if operator == ">":
                return actual > expected
            if operator == ">=":
                return actual >= expected
            if operator == "<":
                return actual < expected
            return actual <= expected
        except TypeError as error:
            raise _type_error(actual, expected, field, operator) from error
    if operator == "in":
        if not isinstance(expected, (str, Mapping, Sequence, Set)):
            raise PredicateEvaluationError(
                "invalid_operand",
                "The right operand of 'in' must be a collection",
                field=field,
                operator=operator,
                expected="collection",
                actual=type(expected).__name__,
            )
        if isinstance(expected, str) and not isinstance(actual, str):
            raise _type_error(actual, expected, field, operator)
        _validate_collection_member(actual, expected, field, operator)
        return actual in expected
    if operator == "contains":
        if actual is None:
            return False
        if not isinstance(actual, (str, Mapping, Sequence, Set)):
            raise PredicateEvaluationError(
                "invalid_operand",
                "The left operand of 'contains' must be a collection",
                field=field,
                operator=operator,
                expected="collection",
                actual=type(actual).__name__,
            )
        if isinstance(actual, str) and not isinstance(expected, str):
            raise _type_error(actual, expected, field, operator)
        _validate_collection_member(expected, actual, field, operator)
        return expected in actual
    if not isinstance(actual, str) or not isinstance(expected, str):
        raise PredicateEvaluationError(
            "type_mismatch",
            f"{operator} requires string operands",
            field=field,
            operator=operator,
            expected="str",
            actual=f"{type(actual).__name__}, {type(expected).__name__}",
        )
    if operator == "startsWith":
        return actual.startswith(expected)
    if operator == "endsWith":
        return actual.endswith(expected)
    try:
        return re.search(expected, actual) is not None
    except re.error as error:
        raise PredicateEvaluationError(
            "invalid_pattern",
            f"Invalid regular expression: {error}",
            field=field,
            operator=operator,
        ) from error


def validate_predicate(
    predicate: Mapping[str, Any] | None,
    schema: DatasetSchema,
) -> None:
    """Validate predicate fields and literal types without reading records."""
    if not predicate:
        return
    for logical in ("and", "or"):
        if logical in predicate:
            for operand in _logical_operands(predicate, logical):
                validate_predicate(operand, schema)
            return
    if "not" in predicate:
        operand = predicate["not"]
        if not isinstance(operand, Mapping):
            raise PredicateEvaluationError(
                "invalid_predicate", "not requires one predicate"
            )
        validate_predicate(operand, schema)
        return
    field, operator, expected = _comparison_parts(predicate)
    if field not in schema.fields:
        raise PredicateEvaluationError(
            "unknown_field",
            f"Unknown predicate field '{field}'",
            field=field,
            operator=operator,
        )
    field_type = schema.fields[field].type
    _validate_literal_type(field_type, operator, expected, field)


def _validate_literal_type(
    field_type: TypeDescriptor,
    operator: str,
    expected: Any,
    field: str,
) -> None:
    if operator not in PREDICATE_OPERATORS:
        raise PredicateEvaluationError(
            "unknown_operator",
            f"Unknown predicate operator '{operator}'",
            field=field,
            operator=operator,
        )
    field_type = _unwrap_nullable(field_type)
    if expected is None:
        if operator == "in":
            raise PredicateEvaluationError(
                "invalid_operand",
                "The right operand of 'in' must be a collection",
                field=field,
                operator=operator,
            )
        if operator in STRING_OPERATORS:
            raise _descriptor_type_error(field_type, expected, field, operator)
        return
    if (
        operator in {">", ">=", "<", "<="}
        and field_type.kind not in _ORDERABLE_TYPE_KINDS
    ):
        raise PredicateEvaluationError(
            "invalid_operand",
            f"{operator} is not supported for {field_type.display()}",
            field=field,
            operator=operator,
            expected="orderable type",
            actual=field_type.display(),
        )
    if operator == "in":
        if not isinstance(expected, (list, tuple, set)):
            raise PredicateEvaluationError(
                "invalid_operand",
                "The right operand of 'in' must be a list, tuple, or set",
                field=field,
                operator=operator,
            )
        for item in expected:
            _require_descriptor_compatible(field_type, item, field, operator)
        return
    if operator == "contains":
        if field_type.kind in {TypeKind.LIST, TypeKind.SET}:
            member_type = field_type.arguments[0]
            assert isinstance(member_type, TypeDescriptor)
            _require_descriptor_compatible(
                _unwrap_nullable(member_type), expected, field, operator
            )
            return
        if field_type.kind == TypeKind.MAP:
            key_type = field_type.arguments[0]
            assert isinstance(key_type, TypeDescriptor)
            _require_descriptor_compatible(
                _unwrap_nullable(key_type), expected, field, operator
            )
            return
        if field_type.kind not in _STRING_TYPE_KINDS:
            raise _descriptor_type_error(field_type, expected, field, operator)
    if operator in STRING_OPERATORS and field_type.kind not in _STRING_TYPE_KINDS:
        raise _descriptor_type_error(field_type, expected, field, operator)
    _require_descriptor_compatible(field_type, expected, field, operator)


def _require_descriptor_compatible(
    descriptor: TypeDescriptor,
    value: Any,
    field: str,
    operator: str,
) -> None:
    try:
        inferred = infer_type(value)
    except NeoQLTypeError as error:
        raise PredicateEvaluationError(
            "type_mismatch",
            f"Cannot type predicate value: {error}",
            field=field,
            operator=operator,
            expected=descriptor.display(),
            actual=type(value).__name__,
        ) from error
    inferred = _unwrap_nullable(inferred)
    if descriptor.kind == TypeKind.ENUM and value in descriptor.arguments:
        return
    if not _descriptors_compatible(descriptor, inferred):
        raise _descriptor_type_error(descriptor, value, field, operator)


def _descriptors_compatible(expected: TypeDescriptor, actual: TypeDescriptor) -> bool:
    expected = _unwrap_nullable(expected)
    actual = _unwrap_nullable(actual)
    if expected.kind == TypeKind.JSON:
        return True
    if expected.kind in _STRING_TYPE_KINDS and actual.kind in _STRING_TYPE_KINDS:
        return True
    if expected.kind in {
        TypeKind.INT,
        TypeKind.FLOAT,
        TypeKind.DECIMAL,
    } and actual.kind in {TypeKind.INT, TypeKind.FLOAT, TypeKind.DECIMAL}:
        return True
    if expected.kind != actual.kind:
        return False
    expected_types = [
        argument
        for argument in expected.arguments
        if isinstance(argument, TypeDescriptor)
    ]
    actual_types = [
        argument
        for argument in actual.arguments
        if isinstance(argument, TypeDescriptor)
    ]
    if len(expected_types) != len(actual_types):
        return not expected_types and not actual_types
    return all(
        _descriptors_compatible(expected_type, actual_type)
        for expected_type, actual_type in zip(expected_types, actual_types, strict=True)
    )


def _unwrap_nullable(descriptor: TypeDescriptor) -> TypeDescriptor:
    if descriptor.kind != TypeKind.NULLABLE:
        return descriptor
    wrapped = descriptor.arguments[0]
    assert isinstance(wrapped, TypeDescriptor)
    return wrapped


def _logical_operands(
    predicate: Mapping[str, Any], operator: str
) -> list[Mapping[str, Any]]:
    operands = predicate[operator]
    if (
        not isinstance(operands, Sequence)
        or isinstance(operands, (str, bytes))
        or not operands
        or not all(isinstance(item, Mapping) for item in operands)
    ):
        raise PredicateEvaluationError(
            "invalid_predicate",
            f"{operator} requires a non-empty predicate list",
            operator=operator,
        )
    return list(operands)


def _comparison_parts(
    predicate: Mapping[str, Any],
) -> tuple[str, str, Any]:
    field = predicate.get("field")
    operator = predicate.get("op")
    if not isinstance(field, str) or not isinstance(operator, str):
        raise PredicateEvaluationError(
            "invalid_predicate",
            "Comparison predicates require field and op strings",
        )
    return field, operator, predicate.get("value")


def _ensure_compatible(
    actual: Any,
    expected: Any,
    field: str | None,
    operator: str,
) -> None:
    if _is_numeric(actual) and _is_numeric(expected):
        return
    if type(actual) is not type(expected):
        raise _type_error(actual, expected, field, operator)


def _is_numeric(value: Any) -> bool:
    return isinstance(value, _NUMERIC_TYPES) and not isinstance(value, bool)


def _validate_collection_member(
    member: Any,
    collection: Any,
    field: str | None,
    operator: str,
) -> None:
    values = collection.keys() if isinstance(collection, Mapping) else collection
    for value in values:
        if value is not None and member is not None:
            _ensure_compatible(member, value, field, operator)


def _type_error(
    actual: Any,
    expected: Any,
    field: str | None,
    operator: str,
) -> PredicateEvaluationError:
    return PredicateEvaluationError(
        "type_mismatch",
        (
            f"Incompatible predicate operands: "
            f"{type(actual).__name__} and {type(expected).__name__}"
        ),
        field=field,
        operator=operator,
        expected=type(actual).__name__,
        actual=type(expected).__name__,
    )


def _descriptor_type_error(
    descriptor: TypeDescriptor,
    value: Any,
    field: str,
    operator: str,
) -> PredicateEvaluationError:
    return PredicateEvaluationError(
        "type_mismatch",
        (f"Predicate value for '{field}' is incompatible with {descriptor.display()}"),
        field=field,
        operator=operator,
        expected=descriptor.display(),
        actual=type(value).__name__,
    )
