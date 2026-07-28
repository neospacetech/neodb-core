from abc import ABC, abstractmethod

from neoql.predicates import evaluate_predicate


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
