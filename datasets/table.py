from .base import BaseDataset

class TableDataset(BaseDataset):
    """A dataset representing a table structure.

    Args:
        BaseDataset (BaseDataset): The base dataset class.
    """
    def __init__(self, name, schema=None):
        self.name = name
        self.schema = schema or {}
        self.columns = list(self.schema)
        self.rows = []

    def insert(self, row):
        if not isinstance(row, dict):
            raise TypeError("Table records must be objects")
        unknown = set(row) - set(self.columns)
        if self.columns and unknown:
            raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")
        self.rows.append(dict(row))

    def query(self, neoql):
        action = neoql.get("action")
        if action == "insert":
            for obj in neoql["objects"]:
                self.insert(obj)
            return {"status": "success", "inserted": len(neoql["objects"])}
        if action != "select":
            raise NotImplementedError(
                "Only 'select' action is supported in query"
            )
        result = self.rows.copy()
        filter_obj = neoql.get("filter")
        if filter_obj:
            result = [row for row in result if self._apply_filter(row, filter_obj)]
        select_fields = neoql.get("select")
        if select_fields:
            result = [{field: row.get(field) for field in select_fields} for row in result]
        order_by = neoql.get("order_by")
        if order_by:
            for order in reversed(order_by):
                field = order["field"]
                result.sort(
                    key=lambda row: row.get(field),
                    reverse=order.get("direction") == "desc",
                )
        offset = neoql.get("offset", 0)
        limit = neoql.get("limit")
        if limit is not None:
            result = result[offset:offset + limit]
        else:
            result = result[offset:]
        return result

    def delete(self, where):
        self.rows = [row for row in self.rows if not where(row)]
