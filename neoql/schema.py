"""Validated dataset schemas and structured constraint diagnostics."""

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .errors import DiagnosticError
from .types import (
    NeoQLTypeError,
    TypeDescriptor,
    TypeKind,
    cast_value,
    parse_type,
)

SUPPORTED_CONSTRAINTS = frozenset(
    {
        "pk",
        "unique",
        "nullable",
        "default",
        "index",
        "vector",
        "searchable",
        "readonly",
    }
)
_MISSING = object()


class SchemaDefinitionError(DiagnosticError):
    """A malformed or internally inconsistent dataset schema."""

    def __init__(self, message: str, *, field: str | None = None):
        self.field = field
        super().__init__(
            "invalid_schema",
            message,
            category="schema_definition",
            phase="compile",
            details={"field": field} if field is not None else {},
        )


class ConstraintViolation(DiagnosticError):
    """A machine-readable record constraint failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        dataset: str,
        field: str | None = None,
        value: Any = _MISSING,
        details: Mapping[str, Any] | None = None,
    ):
        self.code = code
        self.dataset = dataset
        self.field = field
        self.value = value
        diagnostic_details = dict(details or {})
        diagnostic_details["dataset"] = dataset
        if field is not None:
            diagnostic_details["field"] = field
        if self.value is not _MISSING:
            diagnostic_details["value"] = self.value
        super().__init__(
            code,
            message,
            category="constraint_violation",
            phase="runtime",
            details=diagnostic_details,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["dataset"] = self.dataset
        payload["field"] = self.field
        if self.value is not _MISSING:
            payload["value"] = self.value
        return payload


@dataclass(frozen=True, slots=True)
class FieldSchema:
    name: str
    type: TypeDescriptor
    constraints: frozenset[str]
    default: Any = _MISSING

    @property
    def nullable(self) -> bool:
        return "nullable" in self.constraints or self.type.kind == TypeKind.NULLABLE

    @property
    def required(self) -> bool:
        return self.default is _MISSING and not self.nullable


@dataclass(frozen=True, slots=True)
class IndexMetadata:
    field: str
    indexed: bool
    unique: bool
    primary: bool
    vector: bool
    searchable: bool


@dataclass(frozen=True, slots=True)
class DatasetSchema:
    dataset: str
    fields: Mapping[str, FieldSchema]
    indexes: tuple[IndexMetadata, ...]
    primary_key: tuple[str, ...]

    @classmethod
    def from_mapping(
        cls,
        dataset: str,
        schema: Mapping[str, Any] | None,
    ) -> "DatasetSchema":
        field_schemas: dict[str, FieldSchema] = {}
        for name, raw_field in (schema or {}).items():
            if not isinstance(raw_field, Mapping) or "type" not in raw_field:
                raise SchemaDefinitionError("Each field requires a type", field=name)
            raw_type = raw_field["type"]
            try:
                descriptor = (
                    raw_type
                    if isinstance(raw_type, TypeDescriptor)
                    else parse_type(str(raw_type))
                )
            except (NeoQLTypeError, ValueError) as error:
                raise SchemaDefinitionError(
                    f"Invalid type for field '{name}': {error}",
                    field=name,
                ) from error
            constraints, default = _parse_constraints(
                name, raw_field.get("constraints", [])
            )
            if descriptor.kind == TypeKind.NULLABLE:
                constraints.add("nullable")
            if "pk" in constraints and "nullable" in constraints:
                raise SchemaDefinitionError(
                    "Primary-key fields cannot be nullable", field=name
                )
            if constraints & {"pk", "unique"} and descriptor.kind in {
                TypeKind.LIST,
                TypeKind.SET,
                TypeKind.MAP,
                TypeKind.TUPLE,
                TypeKind.JSON,
            }:
                raise SchemaDefinitionError(
                    "Primary and unique fields require scalar values",
                    field=name,
                )
            if default is not _MISSING:
                try:
                    default = cast_value(default, descriptor)
                except NeoQLTypeError as error:
                    raise SchemaDefinitionError(
                        f"Invalid default for field '{name}': {error}",
                        field=name,
                    ) from error
            field_schemas[name] = FieldSchema(
                name,
                descriptor,
                frozenset(constraints),
                default,
            )

        primary_key = tuple(
            name for name, field in field_schemas.items() if "pk" in field.constraints
        )
        indexes = tuple(
            IndexMetadata(
                field=name,
                indexed=bool(
                    field.constraints
                    & {"pk", "unique", "index", "vector", "searchable"}
                ),
                unique=bool(field.constraints & {"pk", "unique"}),
                primary="pk" in field.constraints,
                vector="vector" in field.constraints,
                searchable="searchable" in field.constraints,
            )
            for name, field in field_schemas.items()
            if field.constraints & {"pk", "unique", "index", "vector", "searchable"}
        )
        return cls(dataset, field_schemas, indexes, primary_key)

    def normalize_insert(self, record: Mapping[str, Any]) -> dict[str, Any]:
        self._validate_known_fields(record)
        normalized: dict[str, Any] = {}
        for name, field in self.fields.items():
            if name in record:
                value = record[name]
            elif field.default is not _MISSING:
                value = deepcopy(field.default)
            elif field.nullable:
                value = None
            else:
                raise ConstraintViolation(
                    "required",
                    f"Required field '{name}' is missing",
                    dataset=self.dataset,
                    field=name,
                )
            normalized[name] = self._cast_field(field, value)
        return normalized

    def normalize_update(
        self,
        current: Mapping[str, Any],
        changes: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._validate_known_fields(changes)
        normalized = dict(current)
        for name, value in changes.items():
            field = self.fields[name]
            if (
                "readonly" in field.constraints
                and name in current
                and value != current[name]
            ):
                raise ConstraintViolation(
                    "readonly",
                    f"Readonly field '{name}' cannot be changed",
                    dataset=self.dataset,
                    field=name,
                    value=value,
                )
            normalized[name] = self._cast_field(field, value)
        return normalized

    def validate_records(self, records: Sequence[Mapping[str, Any]]) -> None:
        if self.primary_key:
            seen_primary: dict[tuple[Any, ...], int] = {}
            for index, record in enumerate(records):
                key = tuple(record[field] for field in self.primary_key)
                if any(value is None for value in key):
                    raise ConstraintViolation(
                        "primary_key_null",
                        "Primary-key values cannot be null",
                        dataset=self.dataset,
                        field=", ".join(self.primary_key),
                        value=key,
                    )
                if key in seen_primary:
                    raise ConstraintViolation(
                        "primary_key",
                        "Primary-key value already exists",
                        dataset=self.dataset,
                        field=", ".join(self.primary_key),
                        value=key,
                        details={
                            "first_record": seen_primary[key],
                            "conflicting_record": index,
                        },
                    )
                seen_primary[key] = index

        for name, field in self.fields.items():
            if "unique" not in field.constraints:
                continue
            seen: dict[Any, int] = {}
            for index, record in enumerate(records):
                value = record[name]
                if value is None:
                    continue
                try:
                    previous = seen.get(value)
                except TypeError as error:
                    raise SchemaDefinitionError(
                        "Unique fields must contain hashable values",
                        field=name,
                    ) from error
                if previous is not None:
                    raise ConstraintViolation(
                        "unique",
                        f"Unique value for '{name}' already exists",
                        dataset=self.dataset,
                        field=name,
                        value=value,
                        details={
                            "first_record": previous,
                            "conflicting_record": index,
                        },
                    )
                seen[value] = index

    def _validate_known_fields(self, record: Mapping[str, Any]) -> None:
        unknown = sorted(set(record) - set(self.fields))
        if unknown:
            raise ConstraintViolation(
                "unknown_field",
                f"Unknown fields: {', '.join(unknown)}",
                dataset=self.dataset,
                field=unknown[0] if len(unknown) == 1 else None,
                details={"fields": unknown},
            )

    def _cast_field(self, field: FieldSchema, value: Any) -> Any:
        if value is None:
            if field.nullable:
                return None
            raise ConstraintViolation(
                "null",
                f"Field '{field.name}' cannot be null",
                dataset=self.dataset,
                field=field.name,
                value=None,
            )
        try:
            return cast_value(value, field.type)
        except NeoQLTypeError as error:
            raise ConstraintViolation(
                "type",
                f"Invalid value for field '{field.name}': {error}",
                dataset=self.dataset,
                field=field.name,
                value=value,
                details={"expected": field.type.display()},
            ) from error


def _parse_constraints(field: str, raw_constraints: Any) -> tuple[set[str], Any]:
    if not isinstance(raw_constraints, (list, tuple)):
        raise SchemaDefinitionError("Field constraints must be a list", field=field)
    constraints: set[str] = set()
    default: Any = _MISSING
    for raw_constraint in raw_constraints:
        if isinstance(raw_constraint, str):
            name = raw_constraint
            arguments: list[Any] = []
        elif isinstance(raw_constraint, Mapping):
            raw_name = raw_constraint.get("name")
            arguments = raw_constraint.get("arguments", [])
            if not isinstance(raw_name, str) or not isinstance(arguments, list):
                raise SchemaDefinitionError(
                    "Invalid constraint declaration", field=field
                )
            name = raw_name
        else:
            raise SchemaDefinitionError("Invalid constraint declaration", field=field)
        name = name.lower()
        if name not in SUPPORTED_CONSTRAINTS:
            raise SchemaDefinitionError(f"Unknown constraint '{name}'", field=field)
        if name in constraints:
            raise SchemaDefinitionError(f"Duplicate constraint '{name}'", field=field)
        if name == "default":
            if len(arguments) != 1:
                raise SchemaDefinitionError(
                    "default requires exactly one value", field=field
                )
            default = arguments[0]
        elif arguments:
            raise SchemaDefinitionError(
                f"{name} does not accept arguments", field=field
            )
        constraints.add(name)
    return constraints, default
