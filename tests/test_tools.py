import datetime as dt

from src.agent.tools.diagnostics import duplicate_check, null_rate, row_count_diff, value_distribution_diff
from src.agent.tools.lineage import lineage_trace
from src.agent.tools.schema_tools import get_pipeline_schema, get_run_manifest
from src.agent.tools.sql_query import sql_query
from src.agent.tools.verify import verify_finding
from src.pipeline.bugs import BugSpec
from src.pipeline.transform import CLEAN, build_run

RUN_DATE = dt.date(2024, 1, 15)


def test_get_pipeline_schema_lists_expected_tables(conn):
    build_run(conn, "r1", RUN_DATE, bug=CLEAN)
    schema = get_pipeline_schema(conn)
    assert "stg_order_items_enriched" in schema["tables"]
    assert schema["tables"]["stg_order_items_enriched"]["row_count"] == 3


def test_get_run_manifest_never_exposes_bug_type(conn):
    build_run(conn, "r1", RUN_DATE, scenario_label="s1", bug=BugSpec("row_filter_bug", {"excluded_seller_state": "SP"}))
    manifest = get_run_manifest(conn, "r1")
    assert "bug_type" not in manifest
    assert manifest["staging_row_count"] == 1


def test_row_count_diff_flags_dropped_rows(conn):
    build_run(conn, "r1", RUN_DATE, bug=BugSpec("row_filter_bug", {"excluded_seller_state": "SP"}))
    diff = row_count_diff(conn, "r1")
    assert diff["independent_source_count"] == 3  # all 3 items placed on 2024-01-15
    assert diff["staging_row_count"] == 1
    assert diff["staging_vs_source_diff"] == -2


def test_duplicate_check_finds_fanned_out_keys(conn):
    build_run(conn, "r1", RUN_DATE, bug=BugSpec("join_fanout_bug", {"duplicated_category_name": "cama_mesa_banho"}))
    result = duplicate_check(conn, "r1")
    assert result["total_surplus_rows"] == 1
    assert result["duplicated_keys"][0]["order_id"] == "o2"


def test_lineage_trace_shows_source_vs_staging_discrepancy(conn):
    build_run(conn, "r1", RUN_DATE, bug=BugSpec("null_coalesce_bug", {"null_price_seller_id": "s1"}))
    trace = lineage_trace(conn, "r1", "o1")
    item = trace["items"][0]
    assert item["source"]["price"] == 100.0
    assert item["staging_in_this_run"]["price"] is None  # the discrepancy, visible side by side


def test_verify_finding_independently_recomputes_sum(conn):
    build_run(conn, "r1", RUN_DATE, bug=CLEAN)
    result = verify_finding(conn, table="stg_order_items_enriched", run_id="r1", check="sum", column="price")
    assert result["verified_value"] == 230.0  # 100 + 50 + 80


def test_sql_query_rejects_mutating_statements(conn):
    result = sql_query(conn, "DELETE FROM stg_order_items_enriched")
    assert result["is_error"] is True


def test_sql_query_runs_a_select(conn):
    build_run(conn, "r1", RUN_DATE, bug=CLEAN)
    result = sql_query(conn, "SELECT count(*) AS n FROM stg_order_items_enriched WHERE run_id = 'r1'")
    assert result["is_error"] is False
    assert result["rows"] == [[3]]


def test_null_rate_baseline_comparison(rich_conn):
    bug = BugSpec("schema_drift_bug", {"affected_category": "moveis_decoracao"})
    build_run(rich_conn, "suspect", dt.date(2024, 2, 1), bug=bug)
    result = null_rate(rich_conn, "suspect", "category_english")
    assert result["run_null_rate"] > 0
    assert result["baseline_null_rate"] is not None
    assert result["run_null_rate"] > result["baseline_null_rate"]


def test_value_distribution_diff_flags_currency_bug(rich_conn):
    bug = BugSpec("currency_unit_bug", {"affected_seller_state": "SP", "unit_factor": 100})
    build_run(rich_conn, "suspect", dt.date(2024, 2, 1), bug=bug)
    result = value_distribution_diff(rich_conn, "suspect", metric="avg_freight", group_col="seller_state")
    flagged_groups = {a["group"] for a in result["anomalies"]}
    assert "SP" in flagged_groups
