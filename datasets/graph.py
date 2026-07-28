from .base import BaseDataset


class GraphDataset(BaseDataset):
    """A dataset representing a graph structure.

    Args:
        BaseDataset (BaseDataset): The base dataset class.
    """

    def __init__(self, name):
        self.name = name
        self.nodes = {}
        self.edges = []

    def insert(self, obj):
        node_id = obj.get("id")
        self.nodes[node_id] = obj

    def query(self, neoql):
        # NeoQL: select, filter, order_by, limit, offset
        if neoql.get("action") == "insert":
            for obj in neoql["objects"]:
                self.insert(obj)
            return {
                "status": "success",
                "inserted_ids": [obj.get("id") for obj in neoql["objects"]],
            }
        return self._select(neoql)

    def _selection_records(self):
        return list(self.nodes.values())


# Helper for filter logic
