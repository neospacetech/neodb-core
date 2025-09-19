"""A simple NeoDB engine implementation.
"""

from datasets.graph import GraphDataset
from datasets.table import TableDataset
from datasets.kvs import KVSDataset


class NeoDBEngine:
    """A NeoDB engine for managing datasets.
    """
    def __init__(self):
        self.datasets = {}

    def create_dataset(self, name, dtype="graph", schema=None):
        """Create a new dataset.

        Args:
            name (str): The name of the dataset.
            dtype (str, optional): The type of the dataset. Defaults to "graph".
            schema (dict, optional): The schema of the dataset. Defaults to None.

        Returns:
            Dataset: The created dataset object.
        """
        if dtype == "graph":
            self.datasets[name] = GraphDataset(name)
        elif dtype == "table":
            self.datasets[name] = TableDataset(columns=[])
        elif dtype == "kvs":
            self.datasets[name] = KVSDataset()
            
        print(f"Dataset '{name}' of type '{dtype}' created.")
        print(f"Current datasets: {list(self.datasets.keys())}")

        return self.datasets[name]

    def execute_query(self, query):
        """Execute a query against a dataset.

        Args:
            dataset_name (str): The name of the dataset.
            query (dict): The query object.
        Returns:
            list: Query results.
        """
        match query.get("action"):
            case "batch":
                res = []
                for q in query.get("queries", []):
                    res.append(self.execute_query(q))
                return res
            case "create_dataset":
                dataset = self.create_dataset(
                    query["name"],
                    dtype=query.get("type", "graph"),
                    schema=query.get("schema", None)
                )
                return {"status": "success", "dataset": dataset.name}

        dataset = self.datasets.get(query["dataset"])
        if not dataset:
            raise ValueError(f"Dataset '{query['dataset']}' not found")
        return dataset.query(query)