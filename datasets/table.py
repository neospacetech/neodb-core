from .base import BaseDataset

class TableDataset(BaseDataset):
    """A dataset representing a table structure.

    Args:
        BaseDataset (BaseDataset): The base dataset class.
    """
    def __init__(self, columns):
        self.columns = columns
        self.rows = []


    def insert(self, row):
        if len(row) != len(self.columns):
            raise ValueError("Row length does not match columns")
        self.rows.append(row)


    def query(self, neoql):
        if neoql.get("action") != "select":
            raise NotImplementedError(
                "Only 'select' action is supported in query"
            )
        result = self.rows.copy()
        filter_obj = neoql.get("filter")
        if filter_obj:
            result = [row for row in result if self._apply_filter_table(row, self.columns, filter_obj)]
        select_fields = neoql.get("select")
        if select_fields:
            col_idx = [self.columns.index(k) for k in select_fields]
            result = [
                {self.columns[i]: row[i] for i in col_idx}
                for row in result
            ]
        order_by = neoql.get("order_by")
        if order_by:
            result = self._order_by_table(result, self.columns, order_by)
        offset = neoql.get("offset", 0)
        limit = neoql.get("limit")
        if limit is not None:
            result = result[offset:offset + limit]
        else:
            result = result[offset:]
        return result

    def delete(self, where):
        self.rows = [row for row in self.rows if not where(row)]
