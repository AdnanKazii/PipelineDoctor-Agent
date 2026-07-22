import duckdb

from .schema_tools import list_baseline_runs

ALLOWED_NULL_RATE_COLUMNS = {"category_english", "price", "freight_value", "seller_state", "seller_id"}
ALLOWED_GROUP_COLS = {"seller_state", "category_english"}
ALLOWED_METRICS = {"avg_price", "avg_freight", "sum_price"}


def _run_date(conn: duckdb.DuckDBPyConnection, run_id: str):
    row = conn.execute("SELECT run_date FROM runs WHERE run_id = ?", [run_id]).fetchone()
    if row is None:
        raise ValueError(f"No such run_id: {run_id}")
    return row[0]


def row_count_diff(conn: duckdb.DuckDBPyConnection, run_id: str) -> dict:
    """Compares this run's staging/fact row counts against an independent count
    of source order-items placed on that same calendar date. The source count
    is a plain date filter on src_orders/src_order_items — it does not go
    through the pipeline's own (possibly buggy) staging logic, so a mismatch
    here is real signal, not circular reasoning."""
    run_date = _run_date(conn, run_id)

    source_count = conn.execute(
        """
        SELECT count(*) FROM src_order_items oi
        JOIN src_orders o ON o.order_id = oi.order_id
        WHERE CAST(o.order_purchase_timestamp AS DATE) = ?
        """,
        [run_date],
    ).fetchone()[0]

    staging_count = conn.execute(
        "SELECT count(*) FROM stg_order_items_enriched WHERE run_id = ?", [run_id]
    ).fetchone()[0]

    fct_category_items = conn.execute(
        "SELECT sum(item_count) FROM fct_daily_category_sales WHERE run_id = ?", [run_id]
    ).fetchone()[0] or 0

    fct_seller_items = conn.execute(
        "SELECT sum(item_count) FROM fct_daily_seller_summary WHERE run_id = ?", [run_id]
    ).fetchone()[0] or 0

    return {
        "run_date": str(run_date),
        "independent_source_count": source_count,
        "staging_row_count": staging_count,
        "fct_daily_category_sales_item_count_sum": fct_category_items,
        "fct_daily_seller_summary_item_count_sum": fct_seller_items,
        "staging_vs_source_diff": staging_count - source_count,
    }


def null_rate(conn: duckdb.DuckDBPyConnection, run_id: str, column: str) -> dict:
    """Null rate for a staging column in this run, plus the average null rate
    for the same column across clean baseline runs for comparison."""
    if column not in ALLOWED_NULL_RATE_COLUMNS:
        return {"error": f"column must be one of {sorted(ALLOWED_NULL_RATE_COLUMNS)}"}

    total, nulls = conn.execute(
        f"SELECT count(*), count(*) FILTER (WHERE {column} IS NULL) "
        "FROM stg_order_items_enriched WHERE run_id = ?",
        [run_id],
    ).fetchone()
    this_run_rate = (nulls / total) if total else 0.0

    baseline_ids = list_baseline_runs(conn, exclude_run_id=run_id)
    baseline_rate = None
    if baseline_ids:
        placeholders = ", ".join(["?"] * len(baseline_ids))
        b_total, b_nulls = conn.execute(
            f"SELECT count(*), count(*) FILTER (WHERE {column} IS NULL) "
            f"FROM stg_order_items_enriched WHERE run_id IN ({placeholders})",
            baseline_ids,
        ).fetchone()
        baseline_rate = (b_nulls / b_total) if b_total else 0.0

    return {
        "column": column,
        "run_null_count": nulls,
        "run_total": total,
        "run_null_rate": round(this_run_rate, 4),
        "baseline_null_rate": round(baseline_rate, 4) if baseline_rate is not None else None,
    }


def duplicate_check(conn: duckdb.DuckDBPyConnection, run_id: str, limit: int = 20) -> dict:
    """Finds (order_id, order_item_id) keys that appear more than once in this
    run's staging output — the direct fingerprint of a join fan-out."""
    rows = conn.execute(
        """
        SELECT order_id, order_item_id, count(*) AS n
        FROM stg_order_items_enriched
        WHERE run_id = ?
        GROUP BY order_id, order_item_id
        HAVING count(*) > 1
        ORDER BY n DESC
        LIMIT ?
        """,
        [run_id, limit],
    ).fetchall()
    total_surplus = conn.execute(
        """
        SELECT sum(n - 1) FROM (
            SELECT count(*) AS n FROM stg_order_items_enriched
            WHERE run_id = ? GROUP BY order_id, order_item_id
        )
        """,
        [run_id],
    ).fetchone()[0] or 0
    return {
        "duplicated_keys": [{"order_id": r[0], "order_item_id": r[1], "occurrences": r[2]} for r in rows],
        "total_surplus_rows": total_surplus,
    }


def value_distribution_diff(
    conn: duckdb.DuckDBPyConnection, run_id: str, metric: str, group_col: str
) -> dict:
    """Compares this run's per-group aggregate (e.g. avg_freight per
    seller_state) against the mean/stdev of the same aggregate across clean
    baseline runs, flagging groups more than 2 baseline-stdevs away."""
    if metric not in ALLOWED_METRICS or group_col not in ALLOWED_GROUP_COLS:
        return {"error": f"metric must be in {sorted(ALLOWED_METRICS)}, group_col in {sorted(ALLOWED_GROUP_COLS)}"}

    agg_expr = {
        "avg_price": "avg(price)",
        "avg_freight": "avg(freight_value)",
        "sum_price": "sum(price)",
    }[metric]

    this_run = dict(
        conn.execute(
            f"""
            SELECT {group_col}, {agg_expr} AS v
            FROM stg_order_items_enriched
            WHERE run_id = ? AND {group_col} IS NOT NULL
            GROUP BY {group_col}
            """,
            [run_id],
        ).fetchall()
    )

    baseline_ids = list_baseline_runs(conn, exclude_run_id=run_id)
    flags = []
    if baseline_ids:
        placeholders = ", ".join(["?"] * len(baseline_ids))
        per_run_group = conn.execute(
            f"""
            SELECT run_id, {group_col}, {agg_expr} AS v
            FROM stg_order_items_enriched
            WHERE run_id IN ({placeholders}) AND {group_col} IS NOT NULL
            GROUP BY run_id, {group_col}
            """,
            baseline_ids,
        ).fetchall()

        from collections import defaultdict
        import statistics

        by_group: dict[str, list[float]] = defaultdict(list)
        for _rid, g, v in per_run_group:
            by_group[g].append(v)

        for g, this_v in this_run.items():
            history = by_group.get(g)
            if not history or len(history) < 3:
                continue
            mean = statistics.mean(history)
            stdev = statistics.pstdev(history) or (abs(mean) * 0.05 + 1e-9)
            z = (this_v - mean) / stdev
            if abs(z) > 2:
                flags.append({
                    "group": g, "this_run_value": round(this_v, 2),
                    "baseline_mean": round(mean, 2), "baseline_stdev": round(stdev, 2),
                    "z_score": round(z, 2),
                })

    return {
        "metric": metric, "group_col": group_col,
        "this_run": {g: round(v, 2) for g, v in this_run.items()},
        "anomalies": flags,
    }
