from collections.abc import Callable, Iterable, Mapping
from typing import Any, cast

from neoql.errors import UnknownFieldError
from neoql.predicates import validate_predicate
from neoql.schema import DatasetSchema

from .base import BaseDataset


class TableDataset(BaseDataset):
    """A dataset representing a table structure.

    Args:
        BaseDataset (BaseDataset): The base dataset class.
    """

    def __init__(self, name: str, schema: Mapping[str, Any] | None = None):
        self.name = name
        self.schema = DatasetSchema.from_mapping(name, schema)
        self.columns = list(self.schema.fields)
        self.rows: list[dict[str, Any]] = []
        self.index_metadata = self.schema.indexes

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
        if action != "select":
            raise NotImplementedError("Only 'select' action is supported in query")
        result = self.rows.copy()
        filter_obj = neoql.get("filter")
        validate_predicate(filter_obj, self.schema)
        if filter_obj:
            result = [row for row in result if self._apply_filter(row, filter_obj)]
        select_fields = neoql.get("select")
        if select_fields:
            self._validate_query_fields(select_fields)
            result = [
                {field: row.get(field) for field in select_fields} for row in result
            ]
        order_by = neoql.get("order_by")
        if order_by:
            self._validate_query_fields(order["field"] for order in order_by)
            for order in reversed(order_by):
                field = order["field"]
                result.sort(
                    key=lambda row: cast(Any, row.get(field)),
                    reverse=order.get("direction") == "desc",
                )
        offset = neoql.get("offset", 0)
        limit = neoql.get("limit")
        if limit is not None:
            result = result[offset : offset + limit]
        else:
            result = result[offset:]
        return result

    def _validate_query_fields(self, fields: Iterable[str]) -> None:
        for field in fields:
            if field not in self.schema.fields:
                raise UnknownFieldError(self.name, field)

    def delete(self, where):
        self.rows = [row for row in self.rows if not where(row)]
