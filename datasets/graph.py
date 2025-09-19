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
            return {"status": "success", "inserted_ids": [obj.get("id") for obj in neoql["objects"]]}
        result = list(self.nodes.values())
        filter_obj = neoql.get("filter")
        if filter_obj:
            result = [node for node in result if self._apply_filter(node, filter_obj)]
        select_fields = neoql.get("select")
        if select_fields:
            result = [{k: node.get(k) for k in select_fields} for node in result]
        order_by = neoql.get("order_by")
        if order_by:
            for order in reversed(order_by):
                field = order["field"]
                direction = order.get("direction", "asc")
                result.sort(key=lambda x: x.get(field), reverse=(direction=="desc"))
        offset = neoql.get("offset", 0)
        limit = neoql.get("limit")
        if limit is not None:
            result = result[offset:offset+limit]
        else:
            result = result[offset:]
        return result

# Helper for filter logic

