import functools
import time
from typing import Literal

import duckdb
from anthropic import beta_tool

from .tools.diagnostics import duplicate_check, null_rate, row_count_diff, value_distribution_diff
from .tools.lineage import lineage_trace
from .tools.schema_tools import get_pipeline_schema, get_run_manifest
from .tools.sql_query import sql_query
from .tools.verify import verify_finding

NullRateColumn = Literal["category_english", "price", "freight_value", "seller_state", "seller_id"]
DistributionMetric = Literal["avg_price", "avg_freight", "sum_price"]
DistributionGroupCol = Literal["seller_state", "category_english"]
VerifyTable = Literal["stg_order_items_enriched", "fct_daily_category_sales", "fct_daily_seller_summary"]
VerifyCheck = Literal["row_count", "null_rate", "sum", "avg"]


def _traced(trace: list[dict], name: str):
    """Records every tool call (input, output, latency, error) to `trace`,
    independent of anything the model self-reports — this is what the chat
    UI's live tool-trace panel and the benchmark's tool-call metrics read from."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            start = time.monotonic()
            try:
                result = fn(*args, **kwargs)
                is_error = isinstance(result, dict) and result.get("is_error") is True
            except Exception as exc:  # noqa: BLE001 - surfaced to the model as a tool error, not raised
                result = {"is_error": True, "error": str(exc)}
                is_error = True
            trace.append({
                "tool": name,
                "input": kwargs,
                "output": result,
                "is_error": is_error,
                "latency_ms": round((time.monotonic() - start) * 1000, 1),
            })
            return result

        return wrapper

    return decorator


def build_tools(conn: duckdb.DuckDBPyConnection, trace: list[dict]) -> list:
    """Binds every diagnostic tool to this connection and wraps it for
    tracing, returning the list of BetaFunctionTool objects tool_runner needs."""

    @beta_tool(name="get_pipeline_schema")
    @_traced(trace, "get_pipeline_schema")
    def _get_pipeline_schema() -> dict:
        """Lists every table the agent can query, with column names/types and row counts."""
        return get_pipeline_schema(conn)

    @beta_tool(name="get_run_manifest")
    @_traced(trace, "get_run_manifest")
    def _get_run_manifest(run_id: str | None = None) -> dict:
        """Looks up manifest metadata (run_date, scenario_label, staging row count) for
        one run_id, or lists all known runs if run_id is omitted."""
        return get_run_manifest(conn, run_id)

    @beta_tool(name="row_count_diff")
    @_traced(trace, "row_count_diff")
    def _row_count_diff(run_id: str) -> dict:
        """Compares this run's staging/fact row counts against an independent count of
        source order-items placed on the same date. A first-pass anomaly surfacer."""
        return row_count_diff(conn, run_id)

    @beta_tool(name="null_rate")
    @_traced(trace, "null_rate")
    def _null_rate(run_id: str, column: NullRateColumn) -> dict:
        """Null rate for a staging column in this run, plus the average null rate for
        the same column across clean baseline runs, for comparison."""
        return null_rate(conn, run_id, column)

    @beta_tool(name="duplicate_check")
    @_traced(trace, "duplicate_check")
    def _duplicate_check(run_id: str) -> dict:
        """Finds (order_id, order_item_id) keys duplicated in this run's staging output
        -- the fingerprint of a join fan-out."""
        return duplicate_check(conn, run_id)

    @beta_tool(name="value_distribution_diff")
    @_traced(trace, "value_distribution_diff")
    def _value_distribution_diff(
        run_id: str, metric: DistributionMetric, group_col: DistributionGroupCol
    ) -> dict:
        """Compares this run's per-group aggregate (e.g. avg_freight per seller_state)
        against the mean/stdev of the same aggregate across clean baseline runs,
        flagging groups more than 2 baseline-stdevs away."""
        return value_distribution_diff(conn, run_id, metric, group_col)

    @beta_tool(name="lineage_trace")
    @_traced(trace, "lineage_trace")
    def _lineage_trace(run_id: str, order_id: str) -> dict:
        """Shows one order's items at source vs. in this run's staging output, side by
        side, plus what the category should translate to per the reference table."""
        return lineage_trace(conn, run_id, order_id)

    @beta_tool(name="verify_finding")
    @_traced(trace, "verify_finding")
    def _verify_finding(table: VerifyTable, run_id: str, check: VerifyCheck, column: str | None = None) -> dict:
        """Independently re-derives a claimed number via pandas, as a separate code path
        from the SQL used by the other tools. Call this on every number before citing
        it in your final answer."""
        return verify_finding(conn, table, run_id, check, column)

    @beta_tool(name="sql_query")
    @_traced(trace, "sql_query")
    def _sql_query(sql: str) -> dict:
        """Runs an ad hoc read-only SELECT for anything the other tools don't cover.
        Single statement only, results capped, mutating keywords rejected."""
        return sql_query(conn, sql)

    return [
        _get_pipeline_schema, _get_run_manifest, _row_count_diff, _null_rate,
        _duplicate_check, _value_distribution_diff, _lineage_trace,
        _verify_finding, _sql_query,
    ]
