"""A simple NeoDB engine implementation."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from datasets.graph import GraphDataset
from datasets.kvs import KVSDataset
from datasets.table import TableDataset
from neoql.errors import (
    DatasetAlreadyExistsError,
    DatasetNotFoundError,
    EngineError,
    UnsupportedDatasetError,
)


@dataclass(slots=True)
class TransactionFrame:
    id: str
    datasets: dict[str, Any]


class NeoDBEngine:
    """A NeoDB engine for managing datasets."""

    def __init__(self):
        self._committed_datasets: dict[str, Any] = {}
        self._transactions: list[TransactionFrame] = []

    @property
    def datasets(self) -> dict[str, Any]:
        """Return the datasets visible in the current transaction context."""
        if self._transactions:
            return self._transactions[-1].datasets
        return self._committed_datasets

    @property
    def transaction_depth(self) -> int:
        return len(self._transactions)

    @property
    def active_transaction_id(self) -> str | None:
        return self._transactions[-1].id if self._transactions else None

    def begin_transaction(self) -> str:
        transaction_id = str(uuid4())
        self._transactions.append(
            TransactionFrame(transaction_id, deepcopy(self.datasets))
        )
        return transaction_id

    def commit_transaction(self, transaction_id: str | None = None) -> str:
        frame = self._require_transaction(transaction_id)
        self._transactions.pop()
        if self._transactions:
            self._transactions[-1].datasets = frame.datasets
        else:
            self._committed_datasets = frame.datasets
        return frame.id

    def abort_transaction(self, transaction_id: str | None = None) -> str:
        frame = self._require_transaction(transaction_id)
        self._transactions.pop()
        return frame.id

    @contextmanager
    def transaction(self) -> Iterator[str]:
        """Run work in an atomic transaction or nested savepoint."""
        transaction_id = self.begin_transaction()
        try:
            yield transaction_id
        except Exception:
            if self.active_transaction_id == transaction_id:
                self.abort_transaction(transaction_id)
            raise
        else:
            if self.active_transaction_id == transaction_id:
                self.commit_transaction(transaction_id)

    def _require_transaction(
        self,
        transaction_id: str | None,
    ) -> TransactionFrame:
        if not self._transactions:
            raise EngineError(
                "no_active_transaction",
                "No transaction is active",
                details={},
            )
        frame = self._transactions[-1]
        if transaction_id is not None and transaction_id != frame.id:
            raise EngineError(
                "transaction_order",
                "Only the innermost active transaction can be completed",
                details={
                    "requested": transaction_id,
                    "active": frame.id,
                },
            )
        return frame

    def create_dataset(self, name, dtype="graph", schema=None):
        """Create a new dataset.

        Args:
            name (str): The name of the dataset.
            dtype (str, optional): The type of the dataset. Defaults to "graph".
            schema (dict, optional): The schema of the dataset. Defaults to None.

        Returns:
            Dataset: The created dataset object.
        """
        if name in self.datasets:
            raise DatasetAlreadyExistsError(name)
        if dtype == "graph":
            self.datasets[name] = GraphDataset(name)
        elif dtype == "table":
            self.datasets[name] = TableDataset(name=name, schema=schema)
        elif dtype in ("kv", "kvs"):
            self.datasets[name] = KVSDataset()
        else:
            raise UnsupportedDatasetError(dtype)

        return self.datasets[name]

    def execute_query(self, query: Mapping[str, Any]):
        """Execute a query against a dataset.

        Args:
            dataset_name (str): The name of the dataset.
            query (dict): The query object.
        Returns:
            list: Query results.
        """
        initial_transaction = self.active_transaction_id
        try:
            return self._execute_query(query)
        except Exception:
            if (
                initial_transaction is not None
                and self.active_transaction_id == initial_transaction
            ):
                self.abort_transaction(initial_transaction)
            raise

    def _execute_query(self, query: Mapping[str, Any]):
        match query.get("action"):
            case "batch" | "transaction":
                return self._execute_transaction(query.get("queries", []))
            case "create_dataset":
                dataset = self.create_dataset(
                    query["name"],
                    dtype=query.get("type", "graph"),
                    schema=query.get("schema", None),
                )
                return {"status": "success", "dataset": dataset.name}

        dataset = self.datasets.get(query["dataset"])
        if not dataset:
            raise DatasetNotFoundError(query["dataset"])
        return dataset.query(query)

    def _execute_transaction(
        self,
        queries: Any,
    ) -> list[Any]:
        if not isinstance(queries, list):
            raise EngineError(
                "invalid_transaction",
                "Transaction queries must be a list",
                phase="compile",
            )
        transaction_id = self.begin_transaction()
        try:
            results = [self._execute_query(query) for query in queries]
        except Exception:
            if self.active_transaction_id == transaction_id:
                self.abort_transaction(transaction_id)
            raise
        self.commit_transaction(transaction_id)
        return results
