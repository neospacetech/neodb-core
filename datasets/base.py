from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

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

    def _select(self, neoql: Mapping[str, Any]) -> Selection:
        return Selection.from_query(self, neoql)

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
