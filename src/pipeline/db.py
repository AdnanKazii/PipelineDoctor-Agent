import os
from pathlib import Path

import duckdb

DEFAULT_DB_PATH = Path(os.environ.get("PIPELINE_DB_PATH", "data/pipeline.duckdb"))


def get_connection(db_path: Path | str = DEFAULT_DB_PATH, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path), read_only=read_only)
