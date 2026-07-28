"""Schema-aware document dataset."""

from .table import TableDataset


class DocumentDataset(TableDataset):
    """A document collection with the shared schema and Selection contract."""

    storage_type = "document"
