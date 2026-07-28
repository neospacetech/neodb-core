from abc import ABC, abstractmethod


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
        if not filter_obj:
            return True
        if "and" in filter_obj:
            return all(BaseDataset._apply_filter(obj, f) for f in filter_obj["and"])
        if "or" in filter_obj:
            return any(BaseDataset._apply_filter(obj, f) for f in filter_obj["or"])
        if "not" in filter_obj:
            return not BaseDataset._apply_filter(obj, filter_obj["not"])
        field = filter_obj.get("field")
        op = filter_obj.get("op")
        value = filter_obj.get("value")
        obj_value = obj.get(field)
        if op == "=":
            return obj_value == value
        if op == "!=":
            return obj_value != value
        if op == "in":
            return obj_value in value
        if op == "contains":
            return value in obj_value
        if op == "startsWith":
            return isinstance(obj_value, str) and obj_value.startswith(value)
        if op == "endsWith":
            return isinstance(obj_value, str) and obj_value.endswith(value)
        if op == "matches":
            import re

            return isinstance(obj_value, str) and re.search(value, obj_value) is not None
        if obj_value is None:
            return False
        if op == ">":
            return obj_value > value
        if op == "<":
            return obj_value < value
        if op == ">=":
            return obj_value >= value
        if op == "<=":
            return obj_value <= value
        return False

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
