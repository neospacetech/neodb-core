from .base import BaseDataset

class KVSDataset(BaseDataset):
    """A dataset representing a key-value structure.

    Args:
        BaseDataset (BaseDataset): The base dataset class.
    """
    def __init__(self):
        self.store = {}

    def set(self, key, value):
        self.store[key] = value

    def get(self, key, default=None):
        return self.store.get(key, default)

    def delete(self, key):
        if key in self.store:
            del self.store[key]

    def keys(self):
        return list(self.store.keys())

    def insert(self, obj):
        self.set(obj['key'], obj['value'])

    def query(self, neoql):
        if neoql.get("action") != "select":
            raise NotImplementedError(
                "Only 'select' action is supported in query"
            )
        result = [
            {"key": k, "value": v}
            for k, v in self.store.items()
        ]
        filter_obj = neoql.get("filter")
        if filter_obj:
            result = [item for item in result if self._apply_filter(item, filter_obj)]
        select_fields = neoql.get("select")
        if select_fields:
            result = [
                {k: item.get(k) for k in select_fields}
                for item in result
            ]
        order_by = neoql.get("order_by")
        if order_by:
            for order in reversed(order_by):
                field = order["field"]
                direction = order.get("direction", "asc")
                result.sort(key=lambda x: x.get(field), reverse=(direction == "desc"))
        offset = neoql.get("offset", 0)
        limit = neoql.get("limit")
        if limit is not None:
            result = result[offset:offset + limit]
        else:
            result = result[offset:]
        return result


