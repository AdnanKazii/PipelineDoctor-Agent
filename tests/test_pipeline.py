import datetime as dt

from src.pipeline.bugs import BugSpec
from src.pipeline.transform import CLEAN, build_run

RUN_DATE = dt.date(2024, 1, 15)


def staging_rows(conn, run_id):
    return conn.execute(
        "SELECT * FROM stg_order_items_enriched WHERE run_id = ?", [run_id]
    ).fetchall()


def null_category_count(conn, run_id):
    return conn.execute(
        "SELECT count(*) FROM stg_order_items_enriched WHERE run_id = ? AND category_english IS NULL",
        [run_id],
    ).fetchone()[0]


def test_clean_run(conn):
    n = build_run(conn, "r_clean", RUN_DATE, bug=CLEAN)
    assert n == 3
    assert null_category_count(conn, "r_clean") == 0
    cats = {row[6] for row in staging_rows(conn, "r_clean")}
    assert cats == {"furniture_decor", "bed_bath_table"}


def test_row_filter_bug_drops_one_state(conn):
    bug = BugSpec("row_filter_bug", {"excluded_seller_state": "SP"})
    n = build_run(conn, "r_filter", RUN_DATE, bug=bug)
    assert n == 1  # only o2 (seller RJ) survives; o1/o3 (seller SP) are dropped


def test_join_fanout_bug_duplicates_matching_category(conn):
    bug = BugSpec("join_fanout_bug", {"duplicated_category_name": "cama_mesa_banho"})
    n = build_run(conn, "r_fanout", RUN_DATE, bug=bug)
    assert n == 4  # o2 matches the duplicated translation row twice


def test_schema_drift_bug_nulls_out_affected_category(conn):
    bug = BugSpec("schema_drift_bug", {"affected_category": "moveis_decoracao"})
    n = build_run(conn, "r_drift", RUN_DATE, bug=bug)
    assert n == 3
    assert null_category_count(conn, "r_drift") == 2  # o1, o3


def test_stale_reference_bug_nulls_out_missing_category(conn):
    bug = BugSpec("stale_reference_bug", {"missing_categories": ["moveis_decoracao"]})
    n = build_run(conn, "r_stale", RUN_DATE, bug=bug)
    assert n == 3
    assert null_category_count(conn, "r_stale") == 2


def test_null_coalesce_bug_zeroes_revenue_silently(conn):
    bug = BugSpec("null_coalesce_bug", {"null_price_seller_id": "s1"})
    build_run(conn, "r_nullprice", RUN_DATE, bug=bug)
    price_nulls = conn.execute(
        "SELECT count(*) FROM stg_order_items_enriched WHERE run_id = 'r_nullprice' AND price IS NULL"
    ).fetchone()[0]
    assert price_nulls == 2
    furniture_revenue = conn.execute(
        "SELECT gross_revenue FROM fct_daily_category_sales "
        "WHERE run_id = 'r_nullprice' AND category_english = 'furniture_decor'"
    ).fetchone()[0]
    assert furniture_revenue == 0  # both furniture rows had their price nulled then coalesced to 0


def test_currency_unit_bug_scales_freight_for_one_state(conn):
    bug = BugSpec("currency_unit_bug", {"affected_seller_state": "SP", "unit_factor": 100})
    build_run(conn, "r_currency", RUN_DATE, bug=bug)
    avg_freight_s1 = conn.execute(
        "SELECT avg_freight FROM fct_daily_seller_summary WHERE run_id = 'r_currency' AND seller_id = 's1'"
    ).fetchone()[0]
    assert avg_freight_s1 == 900.0  # (10*100 + 8*100) / 2
    avg_freight_s2 = conn.execute(
        "SELECT avg_freight FROM fct_daily_seller_summary WHERE run_id = 'r_currency' AND seller_id = 's2'"
    ).fetchone()[0]
    assert avg_freight_s2 == 5.0  # unaffected state


def test_timezone_bucketing_bug_leaks_next_day_rows_in(conn):
    bug = BugSpec("timezone_bucketing_bug", {"shift_hours": 3})
    n = build_run(conn, "r_tz", RUN_DATE, bug=bug)
    assert n == 4  # o4 (Jan 16 00:30) shifts back into the Jan 15 run


def test_manifest_records_bug_type(conn):
    bug = BugSpec("row_filter_bug", {"excluded_seller_state": "SP"})
    build_run(conn, "r_manifest", RUN_DATE, scenario_label="unit-test", bug=bug)
    row = conn.execute(
        "SELECT run_date, scenario_label, bug_type FROM runs WHERE run_id = 'r_manifest'"
    ).fetchone()
    assert row == (RUN_DATE, "unit-test", "row_filter_bug")
