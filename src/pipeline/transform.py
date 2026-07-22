import datetime as dt

import duckdb

from .bugs import BugSpec

CLEAN = BugSpec(bug_type="clean")


def _staging_select(bug: BugSpec) -> tuple[str, dict]:
    """Builds the (sql, params) for the staging SELECT, given an optional injected bug.
    Every variant still reads only from src_* tables — no shared source table is mutated,
    so a bug injected into one run cannot leak into any other run's build."""
    bug_type = bug.bug_type
    params: dict = {}

    products_cte = "SELECT product_id, product_category_name FROM src_products"
    translation_cte = "SELECT product_category_name, product_category_name_english FROM src_category_translation"
    extra_seller_filter = ""
    price_expr = "oi.price"
    freight_expr = "oi.freight_value"
    date_filter_expr = "CAST(o.order_purchase_timestamp AS DATE)"

    if bug_type == "schema_drift_bug":
        products_cte = """
            SELECT product_id,
                   CASE WHEN product_category_name = $affected_category
                        THEN product_category_name || ' '
                        ELSE product_category_name END AS product_category_name
            FROM src_products
        """
        params["affected_category"] = bug.params["affected_category"]

    elif bug_type == "stale_reference_bug":
        translation_cte = """
            SELECT product_category_name, product_category_name_english
            FROM src_category_translation
            WHERE product_category_name NOT IN (SELECT UNNEST($missing_categories))
        """
        params["missing_categories"] = bug.params["missing_categories"]

    elif bug_type == "join_fanout_bug":
        translation_cte = """
            SELECT product_category_name, product_category_name_english FROM src_category_translation
            UNION ALL
            SELECT product_category_name, product_category_name_english FROM src_category_translation
            WHERE product_category_name = $duplicated_category_name
        """
        params["duplicated_category_name"] = bug.params["duplicated_category_name"]

    elif bug_type == "row_filter_bug":
        extra_seller_filter = "AND (s.seller_state IS NULL OR s.seller_state != $excluded_seller_state)"
        params["excluded_seller_state"] = bug.params["excluded_seller_state"]

    elif bug_type == "null_coalesce_bug":
        price_expr = "CASE WHEN oi.seller_id = $null_price_seller_id THEN NULL ELSE oi.price END"
        params["null_price_seller_id"] = bug.params["null_price_seller_id"]

    elif bug_type == "currency_unit_bug":
        freight_expr = (
            "CASE WHEN s.seller_state = $affected_seller_state "
            "THEN oi.freight_value * $unit_factor ELSE oi.freight_value END"
        )
        params["affected_seller_state"] = bug.params["affected_seller_state"]
        params["unit_factor"] = bug.params.get("unit_factor", 100)

    elif bug_type == "timezone_bucketing_bug":
        date_filter_expr = f"CAST(o.order_purchase_timestamp - INTERVAL '{int(bug.params.get('shift_hours', 3))} HOUR' AS DATE)"

    elif bug_type != "clean":
        raise ValueError(f"Unknown bug_type: {bug_type}")

    sql = f"""
        WITH products AS ({products_cte}),
             translation AS ({translation_cte})
        SELECT
            $run_id AS run_id,
            oi.order_id,
            oi.order_item_id,
            oi.product_id,
            oi.seller_id,
            s.seller_state,
            t.product_category_name_english AS category_english,
            {price_expr} AS price,
            {freight_expr} AS freight_value,
            o.order_purchase_timestamp
        FROM src_order_items oi
        JOIN src_orders o ON o.order_id = oi.order_id
        JOIN products p ON p.product_id = oi.product_id
        LEFT JOIN src_sellers s ON s.seller_id = oi.seller_id
        LEFT JOIN translation t ON t.product_category_name = p.product_category_name
        WHERE {date_filter_expr} = $run_date
        {extra_seller_filter}
    """
    return sql, params


def build_staging(conn: duckdb.DuckDBPyConnection, run_id: str, run_date: dt.date, bug: BugSpec = CLEAN) -> int:
    conn.execute("DELETE FROM stg_order_items_enriched WHERE run_id = ?", [run_id])
    sql, params = _staging_select(bug)
    params = {"run_id": run_id, "run_date": run_date, **params}
    conn.execute(f"INSERT INTO stg_order_items_enriched {sql}", params)
    return conn.execute(
        "SELECT count(*) FROM stg_order_items_enriched WHERE run_id = ?", [run_id]
    ).fetchone()[0]


def build_facts(conn: duckdb.DuckDBPyConnection, run_id: str, run_date: dt.date) -> None:
    """Aggregates staging into the two fact tables. COALESCE(price, 0) here is a
    deliberate latent flaw: it silently zeroes missing prices instead of excluding
    or flagging them. It's harmless on clean runs (Olist prices are never null) and
    only manifests when null_coalesce_bug injects nulls upstream."""
    conn.execute("DELETE FROM fct_daily_category_sales WHERE run_id = ?", [run_id])
    conn.execute("DELETE FROM fct_daily_seller_summary WHERE run_id = ?", [run_id])

    conn.execute(
        """
        INSERT INTO fct_daily_category_sales
        SELECT
            $run_id, $run_date, category_english, seller_state,
            count(DISTINCT order_id), count(*),
            sum(COALESCE(price, 0)), avg(COALESCE(price, 0))
        FROM stg_order_items_enriched
        WHERE run_id = $run_id
        GROUP BY category_english, seller_state
        """,
        {"run_id": run_id, "run_date": run_date},
    )

    conn.execute(
        """
        INSERT INTO fct_daily_seller_summary
        SELECT
            $run_id, $run_date, seller_id,
            count(DISTINCT order_id), count(*),
            sum(COALESCE(price, 0)), avg(freight_value)
        FROM stg_order_items_enriched
        WHERE run_id = $run_id
        GROUP BY seller_id
        """,
        {"run_id": run_id, "run_date": run_date},
    )


def build_run(
    conn: duckdb.DuckDBPyConnection,
    run_id: str,
    run_date: dt.date,
    scenario_label: str = "",
    bug: BugSpec = CLEAN,
) -> int:
    """Builds one full pipeline run (staging + facts) and records it in the manifest.
    Returns the staging row count."""
    stg_rows = build_staging(conn, run_id, run_date, bug)
    build_facts(conn, run_id, run_date)
    conn.execute("DELETE FROM runs WHERE run_id = ?", [run_id])
    conn.execute(
        "INSERT INTO runs (run_id, run_date, scenario_label, bug_type) VALUES (?, ?, ?, ?)",
        [run_id, run_date, scenario_label, bug.bug_type],
    )
    return stg_rows
