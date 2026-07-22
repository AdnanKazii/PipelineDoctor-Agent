import duckdb

# Tables the agent is allowed to see/query. Deliberately excludes the `runs`
# manifest's bug_type column from anything the agent can read — that column
# only exists for benchmark scoring after the fact.
VISIBLE_TABLES = [
    "src_orders", "src_order_items", "src_products", "src_sellers",
    "src_customers", "src_category_translation",
    "stg_order_items_enriched", "fct_daily_category_sales", "fct_daily_seller_summary",
]


def get_pipeline_schema(conn: duckdb.DuckDBPyConnection) -> dict:
    """Returns column names/types and row counts for every table the agent can query."""
    tables = {}
    for table in VISIBLE_TABLES:
        cols = conn.execute(f"DESCRIBE {table}").fetchall()
        count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        tables[table] = {
            "columns": [{"name": c[0], "type": c[1]} for c in cols],
            "row_count": count,
        }
    return {"tables": tables}


def get_run_manifest(conn: duckdb.DuckDBPyConnection, run_id: str | None = None) -> dict:
    """Lists pipeline runs. Never exposes bug_type — that's ground truth, not
    something a real investigator would have on hand."""
    if run_id is not None:
        row = conn.execute(
            "SELECT run_id, run_date, scenario_label, created_at FROM runs WHERE run_id = ?",
            [run_id],
        ).fetchone()
        if row is None:
            return {"error": f"No such run_id: {run_id}"}
        stg_count = conn.execute(
            "SELECT count(*) FROM stg_order_items_enriched WHERE run_id = ?", [run_id]
        ).fetchone()[0]
        return {
            "run_id": row[0],
            "run_date": str(row[1]),
            "scenario_label": row[2],
            "created_at": str(row[3]),
            "staging_row_count": stg_count,
        }

    rows = conn.execute(
        "SELECT run_id, run_date, scenario_label FROM runs ORDER BY run_date"
    ).fetchall()
    return {"runs": [{"run_id": r[0], "run_date": str(r[1]), "scenario_label": r[2]} for r in rows]}


def list_baseline_runs(conn: duckdb.DuckDBPyConnection, exclude_run_id: str | None = None) -> list[str]:
    """Internal helper (not a tool): the clean historical runs used as a
    'what normal looks like' baseline by the diagnostic tools."""
    rows = conn.execute(
        "SELECT run_id FROM runs WHERE scenario_label = 'baseline' AND run_id != ?",
        [exclude_run_id or ""],
    ).fetchall()
    return [r[0] for r in rows]
