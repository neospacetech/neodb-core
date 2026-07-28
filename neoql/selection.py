"""Immutable lazy selections and executable logical plans."""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import partial
from math import sqrt
from statistics import median, pstdev
from types import MappingProxyType
from typing import Any, TypeAlias, overload

from .errors import EngineError, UnknownFieldError
from .predicates import evaluate_predicate


@dataclass(frozen=True, slots=True)
class FilterPlan:
    predicate: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ProjectionPlan:
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OrderPlan:
    fields: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class OffsetPlan:
    count: int


@dataclass(frozen=True, slots=True)
class LimitPlan:
    count: int


@dataclass(frozen=True, slots=True)
class UniquePlan:
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReversePlan:
    pass


@dataclass(frozen=True, slots=True)
class FlattenPlan:
    field: str


@dataclass(frozen=True, slots=True)
class ExpandPlan:
    field: str


@dataclass(frozen=True, slots=True)
class AlgebraPlan:
    operation: str
    other: "Selection"


@dataclass(frozen=True, slots=True)
class SimilarityPlan:
    field: str
    vector: tuple[float, ...]
    metric: str


@dataclass(frozen=True, slots=True)
class TraversalPlan:
    label: str
    depth: int


@dataclass(frozen=True, slots=True)
class IndexLookupPlan:
    field: str
    value: Any
    predicate: Mapping[str, Any]


PlanNode: TypeAlias = (
    FilterPlan
    | ProjectionPlan
    | OrderPlan
    | OffsetPlan
    | LimitPlan
    | UniquePlan
    | ReversePlan
    | FlattenPlan
    | ExpandPlan
    | AlgebraPlan
    | SimilarityPlan
    | TraversalPlan
    | IndexLookupPlan
)


@dataclass(frozen=True, slots=True, eq=False)
class Selection:
    """A lazy, immutable query over one dataset."""

    _source: Any
    _plan: tuple[PlanNode, ...] = ()

    @property
    def dataset(self) -> str:
        return self._source.name

    @property
    def plan(self) -> tuple[PlanNode, ...]:
        return self._plan

    @classmethod
    def from_query(cls, source: Any, query: Mapping[str, Any]) -> "Selection":
        selection = cls(source)
        predicate = query.get("filter")
        if predicate:
            selection = selection.where(predicate)
        similarity = query.get("similarity")
        if similarity:
            selection = selection.similarity(
                similarity["field"],
                similarity["vector"],
                metric=similarity.get("metric", "cosine"),
            )
        traversal = query.get("traverse")
        if traversal:
            selection = selection.traverse(
                traversal["label"],
                depth=traversal.get("depth", 1),
            )
        fields = query.get("select")
        if fields:
            selection = selection.project(*fields)
        order_by = query.get("order_by")
        if order_by:
            selection = selection.order(
                *((item["field"], item.get("direction", "asc")) for item in order_by)
            )
        offset = query.get("offset", 0)
        if offset:
            selection = selection.offset(offset)
        limit = query.get("limit")
        if limit is not None:
            selection = selection.limit(limit)
        return selection

    def where(self, predicate: Mapping[str, Any]) -> "Selection":
        return self._append(FilterPlan(_freeze_mapping(predicate)))

    def project(self, *fields: str) -> "Selection":
        return self._append(ProjectionPlan(tuple(fields)))

    def order(self, *fields: tuple[str, str]) -> "Selection":
        normalized = tuple((field, direction.lower()) for field, direction in fields)
        if any(direction not in {"asc", "desc"} for _, direction in normalized):
            raise EngineError(
                "invalid_plan",
                "Order direction must be 'asc' or 'desc'",
                phase="plan",
            )
        return self._append(OrderPlan(normalized))

    def sort(self, *fields: str, reverse: bool = False) -> "Selection":
        direction = "desc" if reverse else "asc"
        return self.order(*((field, direction) for field in fields))

    def reverse(self) -> "Selection":
        return self._append(ReversePlan())

    def unique(self, *fields: str) -> "Selection":
        return self._append(UniquePlan(tuple(fields)))

    def distinct(self, *fields: str) -> "Selection":
        return self.unique(*fields)

    def flatten(self, field: str) -> "Selection":
        return self._append(FlattenPlan(field))

    def expand(self, field: str) -> "Selection":
        return self._append(ExpandPlan(field))

    def similarity(
        self,
        field: str,
        vector: Sequence[int | float | Decimal],
        *,
        metric: str = "cosine",
    ) -> "Selection":
        normalized_metric = metric.lower()
        if normalized_metric not in {"cosine", "euclidean"}:
            raise EngineError(
                "invalid_vector_metric",
                f"Unknown vector metric '{metric}'",
                phase="plan",
                details={"metric": metric},
            )
        if not vector or any(
            isinstance(value, bool) or not isinstance(value, (int, float, Decimal))
            for value in vector
        ):
            raise EngineError(
                "invalid_vector",
                "Similarity query requires a non-empty numeric vector",
                phase="plan",
                details={"field": field},
            )
        return self._append(
            SimilarityPlan(
                field,
                tuple(float(value) for value in vector),
                normalized_metric,
            )
        )

    def distance(
        self,
        field: str,
        vector: Sequence[int | float | Decimal],
        *,
        metric: str = "euclidean",
    ) -> "Selection":
        return self.similarity(field, vector, metric=metric)

    def traverse(self, label: str, *, depth: int = 1) -> "Selection":
        if not isinstance(label, str) or not label or depth < 1:
            raise EngineError(
                "invalid_traversal",
                "Traversal requires a relationship label and positive depth",
                phase="plan",
                details={"label": label, "depth": depth},
            )
        return self._append(TraversalPlan(label, depth))

    def group(self, field: str) -> "GroupedSelection":
        return GroupedSelection(self, field)

    def count(self) -> "Aggregation":
        return Aggregation(self, "count")

    def sum(self, field: str) -> "Aggregation":
        return Aggregation(self, "sum", field)

    def avg(self, field: str) -> "Aggregation":
        return Aggregation(self, "avg", field)

    def min(self, field: str) -> "Aggregation":
        return Aggregation(self, "min", field)

    def max(self, field: str) -> "Aggregation":
        return Aggregation(self, "max", field)

    def median(self, field: str) -> "Aggregation":
        return Aggregation(self, "median", field)

    def std(self, field: str) -> "Aggregation":
        return Aggregation(self, "std", field)

    def union(self, other: "Selection") -> "Selection":
        return self._algebra("union", other)

    def intersection(self, other: "Selection") -> "Selection":
        return self._algebra("intersection", other)

    def difference(self, other: "Selection") -> "Selection":
        return self._algebra("difference", other)

    def symmetric_difference(self, other: "Selection") -> "Selection":
        return self._algebra("symmetric_difference", other)

    def product(self, other: "Selection") -> "Selection":
        return self._algebra("product", other)

    def offset(self, count: int) -> "Selection":
        if count < 0:
            raise EngineError(
                "invalid_plan",
                "Offset cannot be negative",
                phase="plan",
            )
        return self._append(OffsetPlan(count))

    def limit(self, count: int) -> "Selection":
        if count < 0:
            raise EngineError(
                "invalid_plan",
                "Limit cannot be negative",
                phase="plan",
            )
        return self._append(LimitPlan(count))

    def consume(self, *, optimize: bool = True) -> list[dict[str, Any]]:
        """Execute the plan and return detached result records."""
        optimized = self.optimized() if optimize else self
        self._source._validate_selection(optimized)
        plan = optimized.plan
        if plan and isinstance(plan[0], IndexLookupPlan):
            result = [dict(record) for record in self._source._index_lookup(plan[0])]
            plan = plan[1:]
        else:
            result = [dict(record) for record in self._source._selection_records()]
        for node in plan:
            if isinstance(node, FilterPlan):
                result = [
                    record
                    for record in result
                    if evaluate_predicate(record, node.predicate)
                ]
            elif isinstance(node, IndexLookupPlan):
                result = [
                    record
                    for record in result
                    if evaluate_predicate(record, node.predicate)
                ]
            elif isinstance(node, ProjectionPlan):
                result = [
                    {field: record.get(field) for field in node.fields}
                    for record in result
                ]
            elif isinstance(node, OrderPlan):
                for field, direction in reversed(node.fields):
                    result.sort(
                        key=partial(_record_value, field=field),
                        reverse=direction == "desc",
                    )
            elif isinstance(node, OffsetPlan):
                result = result[node.count :]
            elif isinstance(node, LimitPlan):
                result = result[: node.count]
            elif isinstance(node, UniquePlan):
                for field in node.fields:
                    if any(field not in record for record in result):
                        raise UnknownFieldError(self.dataset, field)
                result = _unique_records(result, node.fields)
            elif isinstance(node, ReversePlan):
                result = list(reversed(result))
            elif isinstance(node, FlattenPlan):
                result = self._flatten(result, node.field)
            elif isinstance(node, ExpandPlan):
                result = self._expand(result, node.field)
            elif isinstance(node, SimilarityPlan):
                result = self._similarity(result, node)
            elif isinstance(node, TraversalPlan):
                result = self._source._traverse_selection(
                    result,
                    node.label,
                    node.depth,
                )
            else:
                result = self._apply_algebra(result, node)
        return result

    def optimized(self) -> "Selection":
        from .optimizer import optimize_plan

        return Selection(
            self._source, optimize_plan(self._plan, self._source).optimized
        )

    def explain(self) -> dict[str, Any]:
        from .optimizer import optimize_plan

        result = optimize_plan(self._plan, self._source)
        return {"dataset": self.dataset, **result.to_dict()}

    def _append(self, node: PlanNode) -> "Selection":
        return Selection(self._source, (*self._plan, node))

    def _algebra(self, operation: str, other: "Selection") -> "Selection":
        if not isinstance(other, Selection):
            raise EngineError(
                "invalid_plan",
                "Selection algebra requires another Selection",
                phase="plan",
            )
        return self._append(AlgebraPlan(operation, other))

    def _apply_algebra(
        self,
        left: list[dict[str, Any]],
        node: AlgebraPlan,
    ) -> list[dict[str, Any]]:
        right = node.other.consume()
        if node.operation == "product":
            return [
                {"left": dict(left_record), "right": dict(right_record)}
                for left_record in left
                for right_record in right
            ]
        _validate_compatible_schemas(left, right)
        left_unique = _unique_records(left)
        right_unique = _unique_records(right)
        left_keys = {_record_key(record) for record in left_unique}
        right_keys = {_record_key(record) for record in right_unique}
        if node.operation == "union":
            return _unique_records([*left_unique, *right_unique])
        if node.operation == "intersection":
            return [
                record for record in left_unique if _record_key(record) in right_keys
            ]
        if node.operation == "difference":
            return [
                record
                for record in left_unique
                if _record_key(record) not in right_keys
            ]
        return [
            *(
                record
                for record in left_unique
                if _record_key(record) not in right_keys
            ),
            *(
                record
                for record in right_unique
                if _record_key(record) not in left_keys
            ),
        ]

    def _flatten(
        self,
        records: list[dict[str, Any]],
        field: str,
    ) -> list[dict[str, Any]]:
        flattened = []
        for record in records:
            if field not in record:
                raise UnknownFieldError(self.dataset, field)
            value = record[field]
            if not isinstance(value, (list, tuple, set, frozenset)):
                raise EngineError(
                    "type_mismatch",
                    f"flatten requires collection field '{field}'",
                    details={"dataset": self.dataset, "field": field},
                )
            values = (
                sorted(value, key=repr)
                if isinstance(value, (set, frozenset))
                else value
            )
            for item in values:
                flattened.append({**record, field: item})
        return flattened

    def _expand(
        self,
        records: list[dict[str, Any]],
        field: str,
    ) -> list[dict[str, Any]]:
        expanded = []
        for record in records:
            if field not in record:
                raise UnknownFieldError(self.dataset, field)
            value = record[field]
            if not isinstance(value, Mapping):
                raise EngineError(
                    "type_mismatch",
                    f"expand requires object field '{field}'",
                    details={"dataset": self.dataset, "field": field},
                )
            parent = {key: item for key, item in record.items() if key != field}
            collisions = sorted(set(parent) & set(value))
            if collisions:
                raise EngineError(
                    "schema_mismatch",
                    f"Expanded field '{field}' would overwrite fields",
                    phase="plan",
                    details={"dataset": self.dataset, "fields": collisions},
                )
            expanded.append({**parent, **value})
        return expanded

    def _similarity(
        self,
        records: list[dict[str, Any]],
        node: SimilarityPlan,
    ) -> list[dict[str, Any]]:
        ranked = []
        for record in records:
            if node.field not in record:
                raise UnknownFieldError(self.dataset, node.field)
            raw_vector = record[node.field]
            if raw_vector is None:
                continue
            if not isinstance(raw_vector, (list, tuple)) or len(raw_vector) != len(
                node.vector
            ):
                raise EngineError(
                    "vector_dimension",
                    f"Vector field '{node.field}' has incompatible dimensions",
                    details={
                        "dataset": self.dataset,
                        "field": node.field,
                        "expected": len(node.vector),
                    },
                )
            try:
                vector = tuple(float(value) for value in raw_vector)
            except (TypeError, ValueError) as error:
                raise EngineError(
                    "invalid_vector",
                    f"Vector field '{node.field}' contains non-numeric values",
                    details={"dataset": self.dataset, "field": node.field},
                ) from error
            distance, similarity = _vector_score(vector, node.vector, node.metric)
            ranked.append(
                {
                    **record,
                    "_distance": distance,
                    "_similarity": similarity,
                }
            )
        ranked.sort(key=lambda record: record["_distance"])
        return ranked

    def __add__(self, other: "Selection") -> "Selection":
        return self.union(other)

    def __and__(self, other: "Selection") -> "Selection":
        return self.intersection(other)

    def __sub__(self, other: "Selection") -> "Selection":
        return self.difference(other)

    def __xor__(self, other: "Selection") -> "Selection":
        return self.symmetric_difference(other)

    def __mul__(self, other: "Selection") -> "Selection":
        return self.product(other)

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.consume())

    def __len__(self) -> int:
        return len(self.consume())

    @overload
    def __getitem__(self, index: int) -> dict[str, Any]: ...

    @overload
    def __getitem__(self, index: slice) -> list[dict[str, Any]]: ...

    def __getitem__(self, index: int | slice) -> dict[str, Any] | list[dict[str, Any]]:
        return self.consume()[index]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Selection):
            return self.consume() == other.consume()
        if isinstance(other, Sequence):
            return self.consume() == list(other)
        return False

    def __repr__(self) -> str:
        return f"Selection(dataset={self.dataset!r}, plan={self._plan!r})"


@dataclass(frozen=True, slots=True)
class GroupedSelection:
    """A lazy Selection partitioned by one field."""

    selection: Selection
    field: str

    def consume(self) -> list[dict[str, Any]]:
        self.selection._source._validate_aggregation(None, self.field)
        return [
            {self.field: value, "records": records}
            for value, records in _group_records(
                self.selection.consume(),
                self.field,
                self.selection.dataset,
            )
        ]

    def count(self) -> "Aggregation":
        return Aggregation(self.selection, "count", group_field=self.field)

    def sum(self, field: str) -> "Aggregation":
        return Aggregation(self.selection, "sum", field, self.field)

    def avg(self, field: str) -> "Aggregation":
        return Aggregation(self.selection, "avg", field, self.field)

    def min(self, field: str) -> "Aggregation":
        return Aggregation(self.selection, "min", field, self.field)

    def max(self, field: str) -> "Aggregation":
        return Aggregation(self.selection, "max", field, self.field)

    def median(self, field: str) -> "Aggregation":
        return Aggregation(self.selection, "median", field, self.field)

    def std(self, field: str) -> "Aggregation":
        return Aggregation(self.selection, "std", field, self.field)


@dataclass(frozen=True, slots=True)
class Aggregation:
    """A scalar or grouped aggregation that executes only when consumed."""

    selection: Selection
    operation: str
    field: str | None = None
    group_field: str | None = None

    def consume(self) -> Any:
        self.selection._source._validate_aggregation(self.field, self.group_field)
        records = self.selection.consume()
        if self.group_field is None:
            return _aggregate(
                records, self.operation, self.field, self.selection.dataset
            )

        return [
            {
                self.group_field: group_value,
                self.operation: _aggregate(
                    group_records,
                    self.operation,
                    self.field,
                    self.selection.dataset,
                ),
            }
            for group_value, group_records in _group_records(
                records,
                self.group_field,
                self.selection.dataset,
            )
        ]

    def __repr__(self) -> str:
        grouped = (
            f", group_field={self.group_field!r}"
            if self.group_field is not None
            else ""
        )
        return (
            f"Aggregation(dataset={self.selection.dataset!r}, "
            f"operation={self.operation!r}, field={self.field!r}{grouped})"
        )


def _aggregate(
    records: list[dict[str, Any]],
    operation: str,
    field: str | None,
    dataset: str,
) -> Any:
    if operation == "count":
        return len(records)
    assert field is not None
    if any(field not in record for record in records):
        raise UnknownFieldError(dataset, field)
    values = [record[field] for record in records if record[field] is not None]
    if not values:
        return 0 if operation == "sum" else None
    if operation in {"sum", "avg", "median", "std"} and any(
        isinstance(value, bool) or not isinstance(value, (int, float, Decimal))
        for value in values
    ):
        raise EngineError(
            "invalid_aggregation",
            f"{operation} requires numeric field '{field}'",
            details={"dataset": dataset, "field": field, "operation": operation},
        )
    try:
        if operation == "sum":
            return sum(values)
        if operation == "avg":
            return sum(values) / len(values)
        if operation == "min":
            return min(values)
        if operation == "max":
            return max(values)
        if operation == "median":
            return median(values)
        return pstdev(values)
    except TypeError as error:
        raise EngineError(
            "invalid_aggregation",
            f"{operation} cannot compare values in field '{field}'",
            details={"dataset": dataset, "field": field, "operation": operation},
        ) from error


def _group_records(
    records: list[dict[str, Any]],
    field: str,
    dataset: str,
) -> list[tuple[Any, list[dict[str, Any]]]]:
    groups: dict[Any, tuple[Any, list[dict[str, Any]]]] = {}
    for record in records:
        if field not in record:
            raise UnknownFieldError(dataset, field)
        value = record[field]
        key = _value_key(value)
        if key not in groups:
            groups[key] = (value, [])
        groups[key][1].append(record)
    return list(groups.values())


def _vector_score(
    left: tuple[float, ...],
    right: tuple[float, ...],
    metric: str,
) -> tuple[float, float]:
    if metric == "euclidean":
        distance = sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))
        return distance, 1.0 / (1.0 + distance)
    left_norm = sqrt(sum(value * value for value in left))
    right_norm = sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise EngineError(
            "invalid_vector",
            "Cosine similarity is undefined for zero vectors",
            details={"metric": metric},
        )
    similarity = sum(a * b for a, b in zip(left, right, strict=True)) / (
        left_norm * right_norm
    )
    return 1.0 - similarity, similarity


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType({key: _freeze(item) for key, item in value.items()})


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _record_value(record: Mapping[str, Any], *, field: str) -> Any:
    return record.get(field)


def _unique_records(
    records: list[dict[str, Any]],
    fields: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    unique = []
    seen = set()
    for record in records:
        key = (
            tuple(_value_key(record.get(field)) for field in fields)
            if fields
            else _record_key(record)
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


def _record_key(record: Mapping[str, Any]) -> Any:
    return tuple(
        (key, _value_key(value))
        for key, value in sorted(record.items(), key=lambda item: item[0])
    )


def _value_key(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _record_key(value)
    if isinstance(value, (list, tuple)):
        return tuple(_value_key(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_value_key(item) for item in value)
    try:
        hash(value)
    except TypeError:
        return repr(value)
    return value


def _validate_compatible_schemas(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
) -> None:
    left_schemas = {frozenset(record) for record in left}
    right_schemas = {frozenset(record) for record in right}
    if len(left_schemas) > 1 or len(right_schemas) > 1:
        raise EngineError(
            "schema_mismatch",
            "Selection contains records with inconsistent schemas",
            phase="plan",
        )
    if left_schemas and right_schemas and left_schemas != right_schemas:
        raise EngineError(
            "schema_mismatch",
            "Selection algebra requires identical field schemas",
            phase="plan",
            details={
                "left": sorted(next(iter(left_schemas))),
                "right": sorted(next(iter(right_schemas))),
            },
        )
