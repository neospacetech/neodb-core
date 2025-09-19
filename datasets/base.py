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
        if "and" in filter_obj:
            return all(BaseDataset._apply_filter(obj, f) for f in filter_obj["and"])
        if "or" in filter_obj:
            return any(BaseDataset._apply_filter(obj, f) for f in filter_obj["or"])
        field = filter_obj.get("field")
        op = filter_obj.get("op")
        value = filter_obj.get("value")
        obj_value = obj.get(field)
        if op == "=":
            return obj_value == value
        if op == ">":
            return obj_value > value
        if op == "<":
            return obj_value < value
        if op == ">=":
            return obj_value >= value
        if op == "<=":
            return obj_value <= value
        if op == "!=":
            return obj_value != value
        return False

    @staticmethod
    def _order_by_table(result, columns, order_by):
        for order in reversed(order_by):
            field = order["field"]
            direction = order.get("direction", "asc")
            idx = columns.index(field)
            result.sort(key=lambda x: x[idx] if isinstance(x, list) else x.get(field), reverse=(direction == "desc"))
        return result