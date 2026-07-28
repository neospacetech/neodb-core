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
        self.set(obj["key"], obj["value"])

    def query(self, neoql):
        action = neoql.get("action")
        if action == "insert":
            for obj in neoql["objects"]:
                self.insert(obj)
            return {"status": "success", "inserted": len(neoql["objects"])}
        if action != "select":
            raise NotImplementedError("Only 'select' action is supported in query")
        return self._select(neoql)

    def _selection_records(self):
        return [{"key": key, "value": value} for key, value in self.store.items()]
