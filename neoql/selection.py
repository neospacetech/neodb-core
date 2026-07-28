"""Immutable lazy selections and executable logical plans."""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from types import MappingProxyType
from typing import Any, TypeAlias, overload

from .errors import EngineError
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


PlanNode: TypeAlias = FilterPlan | ProjectionPlan | OrderPlan | OffsetPlan | LimitPlan


@dataclass(frozen=True, slots=True, eq=False)
class Selection(Sequence[dict[str, Any]]):
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

    def consume(self) -> list[dict[str, Any]]:
        """Execute the plan and return detached result records."""
        self._source._validate_selection(self)
        result = [dict(record) for record in self._source._selection_records()]
        for node in self._plan:
            if isinstance(node, FilterPlan):
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
            else:
                result = result[: node.count]
        return result

    def _append(self, node: PlanNode) -> "Selection":
        return Selection(self._source, (*self._plan, node))

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
