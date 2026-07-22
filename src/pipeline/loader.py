from pathlib import Path

import duckdb

from .schema import init_schema

DEFAULT_DATA_DIR = Path("data")

_SOURCE_FILES = {
    "src_orders": "olist_orders_dataset.csv",
    "src_order_items": "olist_order_items_dataset.csv",
    "src_products": "olist_products_dataset.csv",
    "src_sellers": "olist_sellers_dataset.csv",
    "src_customers": "olist_customers_dataset.csv",
    "src_category_translation": "product_category_name_translation.csv",
}

# Only these columns are pulled from each CSV (the source files carry extra
# columns, e.g. product dimensions, that this pipeline has no use for).
_SOURCE_COLUMNS = {
    "src_orders": [
        "order_id", "customer_id", "order_status", "order_purchase_timestamp",
        "order_approved_at", "order_delivered_carrier_date",
        "order_delivered_customer_date", "order_estimated_delivery_date",
    ],
    "src_order_items": [
        "order_id", "order_item_id", "product_id", "seller_id",
        "shipping_limit_date", "price", "freight_value",
    ],
    "src_products": ["product_id", "product_category_name"],
    "src_sellers": ["seller_id", "seller_zip_code_prefix", "seller_city", "seller_state"],
    "src_customers": [
        "customer_id", "customer_unique_id", "customer_zip_code_prefix",
        "customer_city", "customer_state",
    ],
    "src_category_translation": ["product_category_name", "product_category_name_english"],
}


def load_sources(conn: duckdb.DuckDBPyConnection, data_dir: Path | str = DEFAULT_DATA_DIR) -> None:
    """Loads the raw Olist CSVs into the src_* tables, replacing any existing contents."""
    init_schema(conn)
    data_dir = Path(data_dir)
    for table, filename in _SOURCE_FILES.items():
        csv_path = data_dir / filename
        if not csv_path.exists():
            raise FileNotFoundError(
                f"Missing source CSV: {csv_path}. Fetch the Olist dataset into {data_dir}/ first."
            )
        cols = ", ".join(_SOURCE_COLUMNS[table])
        conn.execute(f"DELETE FROM {table}")
        conn.execute(
            f"INSERT INTO {table} SELECT {cols} FROM read_csv_auto(?, header=true)",
            [str(csv_path)],
        )


def source_row_counts(conn: duckdb.DuckDBPyConnection) -> dict[str, int]:
    return {
        table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in _SOURCE_FILES
    }
