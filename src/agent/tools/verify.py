import duckdb

ALLOWED_TABLES = {"stg_order_items_enriched", "fct_daily_category_sales", "fct_daily_seller_summary"}
ALLOWED_CHECKS = {"row_count", "null_rate", "sum", "avg"}


def verify_finding(
    conn: duckdb.DuckDBPyConnection, table: str, run_id: str, check: str, column: str | None = None
) -> dict:
    """Independently re-derives a claimed number using pandas over the raw
    rows, rather than re-running the same SQL aggregation the diagnostic tools
    used to produce it. Every numeric claim in a final diagnosis must be
    passed through this tool before being presented — it's a genuine second
    code path, not just re-asking the same question."""
    if table not in ALLOWED_TABLES:
        return {"error": f"table must be one of {sorted(ALLOWED_TABLES)}"}
    if check not in ALLOWED_CHECKS:
        return {"error": f"check must be one of {sorted(ALLOWED_CHECKS)}"}
    if check in {"null_rate", "sum", "avg"} and not column:
        return {"error": f"check '{check}' requires a column"}

    df = conn.execute(f"SELECT * FROM {table} WHERE run_id = ?", [run_id]).df()
    if column is not None and column not in df.columns:
        return {"error": f"no such column '{column}' on {table}"}

    if check == "row_count":
        value = int(len(df))
    elif check == "null_rate":
        value = float(df[column].isna().mean()) if len(df) else 0.0
    elif check == "sum":
        value = float(df[column].fillna(0).sum())
    elif check == "avg":
        value = float(df[column].mean()) if len(df) else None

    return {"table": table, "run_id": run_id, "check": check, "column": column, "verified_value": value}
