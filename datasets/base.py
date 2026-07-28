from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from neoql.errors import InvalidTraversalError
from neoql.predicates import evaluate_predicate
from neoql.selection import Selection


class BaseDataset(ABC):
    """Base class for datasets.

    Args:
        ABC (ABC): Abstract Base Class.
    """

    @abstractmethod
    def insert(self, obj):
        pass

    @abstractmethod
    def query(self, neoql):
        pass

    @abstractmethod
    def _selection_records(self) -> list[Mapping[str, Any]]:
        """Return current source records when a Selection is consumed."""
        pass

    def _validate_selection(self, selection: Selection) -> None:
        """Validate a plan before reading source records."""
        return None

    def _validate_aggregation(
        self,
        field: str | None,
        group_field: str | None,
    ) -> None:
        """Validate aggregate fields before reading source records."""
        return None

    def _traverse_selection(
        self,
        records: list[dict[str, Any]],
        label: str,
        depth: int,
        predicate: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        raise InvalidTraversalError(
            "Traversal requires a graph dataset",
            dataset=getattr(self, "name", None),
            label=label,
            depth=depth,
        )

    def _index_lookup(self, plan: Any) -> list[Mapping[str, Any]]:
        return [
            record
            for record in self._selection_records()
            if evaluate_predicate(record, plan.predicate)
        ]

    def _select(self, neoql: Mapping[str, Any]) -> Any:
        result: Any = Selection.from_query(self, neoql)
        if neoql.get("explain"):
            return result.explain()
        group_field = neoql.get("group_by")
        if group_field is not None:
            result = result.group(group_field)
        aggregate = neoql.get("aggregate")
        if aggregate is not None:
            arguments = [aggregate["field"]] if "field" in aggregate else []
            result = getattr(result, aggregate["operation"])(*arguments)
        return result

    @staticmethod
    def _apply_filter(obj, filter_obj):
        return evaluate_predicate(obj, filter_obj)

    @staticmethod
    def _order_by_table(result, columns, order_by):
        for order in reversed(order_by):
            field = order["field"]
            direction = order.get("direction", "asc")
            idx = columns.index(field)
            result.sort(
                key=lambda x: x[idx] if isinstance(x, list) else x.get(field),
                reverse=(direction == "desc"),
            )
        return result
