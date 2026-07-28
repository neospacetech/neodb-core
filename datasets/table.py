from collections.abc import Callable, Iterable, Mapping
from typing import Any

from neoql.errors import EngineError, UnknownFieldError
from neoql.predicates import validate_predicate
from neoql.schema import DatasetSchema
from neoql.selection import (
    ExpandPlan,
    FilterPlan,
    FlattenPlan,
    IndexLookupPlan,
    OrderPlan,
    ProjectionPlan,
    Selection,
    SimilarityPlan,
    UniquePlan,
)
from neoql.types import TypeKind

from .base import BaseDataset


class TableDataset(BaseDataset):
    """A dataset representing a table structure.

    Args:
        BaseDataset (BaseDataset): The base dataset class.
    """

    storage_type = "table"

    def __init__(self, name: str, schema: Mapping[str, Any] | None = None):
        self.name = name
        self.schema = DatasetSchema.from_mapping(name, schema)
        self.columns = list(self.schema.fields)
        self.rows: list[dict[str, Any]] = []
        self.index_metadata = self.schema.indexes
        self._indexes: dict[str, dict[Any, list[int]]] = {}
        self._rebuild_indexes()

    def insert(self, row: Mapping[str, Any]) -> dict[str, Any]:
        inserted = self.insert_many([row])
        return inserted[0]

    def insert_many(self, rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        if not all(isinstance(row, Mapping) for row in rows):
            raise TypeError("Table records must be objects")
        normalized = [self.schema.normalize_insert(row) for row in rows]
        candidates = [*self.rows, *normalized]
        self.schema.validate_records(candidates)
        self.rows.extend(normalized)
        self._rebuild_indexes()
        return [dict(row) for row in normalized]

    def update(
        self,
        changes: Mapping[str, Any],
        where: Callable[[Mapping[str, Any]], bool] | None = None,
    ) -> int:
        predicate = where or (lambda _row: True)
        matched = [predicate(row) for row in self.rows]
        candidates = [
            self.schema.normalize_update(row, changes) if should_update else dict(row)
            for row, should_update in zip(self.rows, matched, strict=True)
        ]
        self.schema.validate_records(candidates)
        updated = sum(matched)
        self.rows = candidates
        self._rebuild_indexes()
        return updated

    def query(self, neoql):
        action = neoql.get("action")
        if action == "insert":
            self.insert_many(neoql["objects"])
            return {"status": "success", "inserted": len(neoql["objects"])}
        if action == "update":
            filter_obj = neoql.get("filter")
            validate_predicate(filter_obj, self.schema)
            updated = self.update(
                neoql.get("values", {}),
                where=(
                    lambda row: (
                        self._apply_filter(row, filter_obj) if filter_obj else True
                    )
                ),
            )
            return {"status": "success", "updated": updated}
        if action == "delete":
            filter_obj = neoql.get("filter")
            validate_predicate(filter_obj, self.schema)
            deleted = self.delete(
                where=(
                    lambda row: (
                        self._apply_filter(row, filter_obj) if filter_obj else True
                    )
                )
            )
            return {"status": "success", "deleted": deleted}
        if action != "select":
            raise NotImplementedError(
                "Only 'select', 'update', and 'delete' actions are supported in query"
            )
        return self._select(neoql)

    def _selection_records(self):
        return self.rows.copy()

    def _validate_selection(self, selection: Selection) -> None:
        computed_fields: set[str] = set()
        for node in selection.plan:
            if isinstance(node, (FilterPlan, IndexLookupPlan)):
                validate_predicate(node.predicate, self.schema)
            elif isinstance(node, ProjectionPlan):
                self._validate_query_fields(
                    field for field in node.fields if field not in computed_fields
                )
            elif isinstance(node, OrderPlan):
                self._validate_query_fields(
                    field
                    for field, _direction in node.fields
                    if field not in computed_fields
                )
            elif isinstance(node, UniquePlan) and node.fields:
                self._validate_query_fields(
                    field for field in node.fields if field not in computed_fields
                )
            elif isinstance(node, FlattenPlan):
                self._validate_query_fields((node.field,))
                if self.schema.fields[node.field].type.kind not in {
                    TypeKind.LIST,
                    TypeKind.SET,
                    TypeKind.TUPLE,
                }:
                    raise EngineError(
                        "type_mismatch",
                        f"flatten requires collection field '{node.field}'",
                        phase="plan",
                        details={"dataset": self.name, "field": node.field},
                    )
            elif isinstance(node, ExpandPlan):
                self._validate_query_fields((node.field,))
                if self.schema.fields[node.field].type.kind not in {
                    TypeKind.MAP,
                    TypeKind.JSON,
                }:
                    raise EngineError(
                        "type_mismatch",
                        f"expand requires object field '{node.field}'",
                        phase="plan",
                        details={"dataset": self.name, "field": node.field},
                    )
            elif isinstance(node, SimilarityPlan):
                self._validate_query_fields((node.field,))
                field = self.schema.fields[node.field]
                if "vector" not in field.constraints:
                    raise EngineError(
                        "invalid_vector_field",
                        f"Field '{node.field}' is not a vector index",
                        phase="plan",
                        details={"dataset": self.name, "field": node.field},
                    )
                if (
                    field.vector_dimension is not None
                    and len(node.vector) != field.vector_dimension
                ):
                    raise EngineError(
                        "vector_dimension",
                        f"Vector field '{node.field}' requires "
                        f"{field.vector_dimension} dimensions",
                        phase="plan",
                        details={
                            "dataset": self.name,
                            "field": node.field,
                            "dimension": field.vector_dimension,
                        },
                    )
                computed_fields.update({"_distance", "_similarity"})

    def _validate_aggregation(
        self,
        field: str | None,
        group_field: str | None,
    ) -> None:
        self._validate_query_fields(
            name for name in (field, group_field) if name is not None
        )

    def _validate_query_fields(self, fields: Iterable[str]) -> None:
        for field in fields:
            if field not in self.schema.fields:
                raise UnknownFieldError(self.name, field)

    def delete(
        self,
        where: Callable[[Mapping[str, Any]], bool] | None = None,
    ) -> int:
        predicate = where or (lambda _row: True)
        remaining = [row for row in self.rows if not predicate(row)]
        deleted = len(self.rows) - len(remaining)
        self.schema.validate_records(remaining)
        self.rows = remaining
        self._rebuild_indexes()
        return deleted

    def _rebuild_indexes(self) -> None:
        indexes: dict[str, dict[Any, list[int]]] = {}
        for metadata in self.index_metadata:
            if not metadata.indexed or metadata.vector:
                continue
            values: dict[Any, list[int]] = {}
            for position, record in enumerate(self.rows):
                value = record.get(metadata.field)
                try:
                    hash(value)
                except TypeError:
                    continue
                values.setdefault(value, []).append(position)
            indexes[metadata.field] = values
        self._indexes = indexes

    def _index_lookup(self, plan: IndexLookupPlan) -> list[Mapping[str, Any]]:
        positions = self._indexes.get(plan.field, {}).get(plan.value)
        if positions is None:
            return []
        return [self.rows[position] for position in positions]

    def index_snapshot(self) -> dict[str, dict[Any, list[int]]]:
        return {
            field: {value: list(positions) for value, positions in values.items()}
            for field, values in self._indexes.items()
        }
