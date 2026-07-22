import duckdb

SOURCE_DDL = """
CREATE TABLE IF NOT EXISTS src_orders (
    order_id VARCHAR,
    customer_id VARCHAR,
    order_status VARCHAR,
    order_purchase_timestamp TIMESTAMP,
    order_approved_at TIMESTAMP,
    order_delivered_carrier_date TIMESTAMP,
    order_delivered_customer_date TIMESTAMP,
    order_estimated_delivery_date TIMESTAMP
);

CREATE TABLE IF NOT EXISTS src_order_items (
    order_id VARCHAR,
    order_item_id INTEGER,
    product_id VARCHAR,
    seller_id VARCHAR,
    shipping_limit_date TIMESTAMP,
    price DOUBLE,
    freight_value DOUBLE
);

CREATE TABLE IF NOT EXISTS src_products (
    product_id VARCHAR,
    product_category_name VARCHAR
);

CREATE TABLE IF NOT EXISTS src_sellers (
    seller_id VARCHAR,
    seller_zip_code_prefix INTEGER,
    seller_city VARCHAR,
    seller_state VARCHAR
);

CREATE TABLE IF NOT EXISTS src_customers (
    customer_id VARCHAR,
    customer_unique_id VARCHAR,
    customer_zip_code_prefix INTEGER,
    customer_city VARCHAR,
    customer_state VARCHAR
);

CREATE TABLE IF NOT EXISTS src_category_translation (
    product_category_name VARCHAR,
    product_category_name_english VARCHAR
);
"""

PIPELINE_DDL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id VARCHAR PRIMARY KEY,
    run_date DATE,
    scenario_label VARCHAR,
    bug_type VARCHAR,
    created_at TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS stg_order_items_enriched (
    run_id VARCHAR,
    order_id VARCHAR,
    order_item_id INTEGER,
    product_id VARCHAR,
    seller_id VARCHAR,
    seller_state VARCHAR,
    category_english VARCHAR,
    price DOUBLE,
    freight_value DOUBLE,
    order_purchase_timestamp TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fct_daily_category_sales (
    run_id VARCHAR,
    run_date DATE,
    category_english VARCHAR,
    seller_state VARCHAR,
    order_count INTEGER,
    item_count INTEGER,
    gross_revenue DOUBLE,
    avg_item_price DOUBLE
);

CREATE TABLE IF NOT EXISTS fct_daily_seller_summary (
    run_id VARCHAR,
    run_date DATE,
    seller_id VARCHAR,
    order_count INTEGER,
    item_count INTEGER,
    gross_revenue DOUBLE,
    avg_freight DOUBLE
);
"""

# The staging schema a healthy pipeline run is expected to produce.
# schema_diff tool compares a run's actual stg_order_items_enriched columns/types against this.
EXPECTED_STAGING_SCHEMA = {
    "run_id": "VARCHAR",
    "order_id": "VARCHAR",
    "order_item_id": "INTEGER",
    "product_id": "VARCHAR",
    "seller_id": "VARCHAR",
    "seller_state": "VARCHAR",
    "category_english": "VARCHAR",
    "price": "DOUBLE",
    "freight_value": "DOUBLE",
    "order_purchase_timestamp": "TIMESTAMP",
}


def init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(SOURCE_DDL)
    conn.execute(PIPELINE_DDL)
