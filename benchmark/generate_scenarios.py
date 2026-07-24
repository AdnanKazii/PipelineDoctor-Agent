"""Builds the benchmark's scenario runs (opaque scenario_NNN ids, scenario_label
'benchmark' -- never 'baseline', so they can never leak into the diagnostic
tools' baseline-comparison pool) and writes ground truth to
benchmark/fixtures/scenarios.json. Ground truth lives only in this file and is
never read by the agent, which only ever sees the DuckDB tables via its tools.

Usage: python -m benchmark.generate_scenarios
"""

import json
from pathlib import Path

from src.pipeline.bootstrap import MIN_DAILY_ORDERS
from src.pipeline.bugs import CATALOG, BugSpec
from src.pipeline.db import get_connection
from src.pipeline.transform import CLEAN, build_run

FIXTURES_PATH = Path(__file__).parent / "fixtures" / "scenarios.json"

# (bug_type, difficulty) pairs. "dominant" affects the biggest group in that
# day's data (an obvious, easy-to-spot signal); "minor" affects a small group
# (a subtler signal that takes more digging to confirm). timezone/clean have
# no group to vary.
PLAN = [
    ("row_filter_bug", "dominant"), ("row_filter_bug", "dominant"), ("row_filter_bug", "minor"),
    ("join_fanout_bug", "dominant"), ("join_fanout_bug", "minor"), ("join_fanout_bug", "minor"),
    ("schema_drift_bug", "dominant"), ("schema_drift_bug", "minor"), ("schema_drift_bug", "minor"),
    ("stale_reference_bug", "dominant"), ("stale_reference_bug", "minor"), ("stale_reference_bug", "minor"),
    ("null_coalesce_bug", "dominant"), ("null_coalesce_bug", "minor"), ("null_coalesce_bug", "minor"),
    ("currency_unit_bug", "dominant"), ("currency_unit_bug", "minor"), ("currency_unit_bug", "minor"),
    ("timezone_bucketing_bug", "n/a"), ("timezone_bucketing_bug", "n/a"), ("timezone_bucketing_bug", "n/a"),
    ("clean", "n/a"), ("clean", "n/a"), ("clean", "n/a"), ("clean", "n/a"), ("clean", "n/a"), ("clean", "n/a"),
]


def _candidate_dates(conn, exclude_dates: set) -> list:
    rows = conn.execute(
        """
        SELECT CAST(order_purchase_timestamp AS DATE) AS d, count(*) AS n
        FROM src_orders GROUP BY d HAVING n >= ? ORDER BY d
        """,
        [MIN_DAILY_ORDERS],
    ).fetchall()
    return [r[0] for r in rows if r[0] not in exclude_dates]


def _group_for_date(conn, run_date, group_col: str, product_key: bool, pick: str) -> str:
    """Picks the dominant or a minor (non-trivial, >=3 items) group value for
    seller_state or product_category_name on a given date."""
    table_col = "p.product_category_name" if product_key else "s.seller_state"
    join = "JOIN src_products p ON p.product_id = oi.product_id" if product_key else \
        "LEFT JOIN src_sellers s ON s.seller_id = oi.seller_id"
    order = "ASC" if pick == "minor" else "DESC"
    row = conn.execute(
        f"""
        SELECT {table_col} AS g, count(*) AS n
        FROM src_order_items oi
        JOIN src_orders o ON o.order_id = oi.order_id
        {join}
        WHERE CAST(o.order_purchase_timestamp AS DATE) = ? AND {table_col} IS NOT NULL
        GROUP BY g HAVING n >= 3
        ORDER BY n {order}
        LIMIT 1
        """,
        [run_date],
    ).fetchone()
    return row[0] if row else None


def _top_seller(conn, run_date) -> str:
    row = conn.execute(
        """
        SELECT seller_id, count(*) AS n FROM src_order_items oi
        JOIN src_orders o ON o.order_id = oi.order_id
        WHERE CAST(o.order_purchase_timestamp AS DATE) = ?
        GROUP BY seller_id ORDER BY n DESC LIMIT 1
        """,
        [run_date],
    ).fetchone()
    return row[0]


def _build_bug(conn, run_date, bug_type: str, difficulty: str) -> BugSpec:
    if bug_type == "row_filter_bug":
        state = _group_for_date(conn, run_date, "seller_state", False, difficulty)
        return BugSpec(bug_type, {"excluded_seller_state": state})
    if bug_type == "join_fanout_bug":
        cat = _group_for_date(conn, run_date, "product_category_name", True, difficulty)
        return BugSpec(bug_type, {"duplicated_category_name": cat})
    if bug_type == "schema_drift_bug":
        cat = _group_for_date(conn, run_date, "product_category_name", True, difficulty)
        return BugSpec(bug_type, {"affected_category": cat})
    if bug_type == "stale_reference_bug":
        cat = _group_for_date(conn, run_date, "product_category_name", True, difficulty)
        return BugSpec(bug_type, {"missing_categories": [cat]})
    if bug_type == "null_coalesce_bug":
        return BugSpec(bug_type, {"null_price_seller_id": _top_seller(conn, run_date)})
    if bug_type == "currency_unit_bug":
        state = _group_for_date(conn, run_date, "seller_state", False, difficulty)
        return BugSpec(bug_type, {"affected_seller_state": state, "unit_factor": 100})
    if bug_type == "timezone_bucketing_bug":
        return BugSpec(bug_type, {"shift_hours": 3})
    raise ValueError(bug_type)


def main() -> None:
    conn = get_connection()
    existing_dates = {r[0] for r in conn.execute("SELECT run_date FROM runs").fetchall()}
    dates = _candidate_dates(conn, existing_dates)
    if len(dates) < len(PLAN):
        raise RuntimeError(f"Need {len(PLAN)} distinct dates, only {len(dates)} available.")

    ground_truth = []
    for i, (bug_type, difficulty) in enumerate(PLAN, start=1):
        scenario_id = f"scenario_{i:03d}"
        run_date = dates[i - 1]
        bug = CLEAN if bug_type == "clean" else _build_bug(conn, run_date, bug_type, difficulty)
        n_rows = build_run(conn, scenario_id, run_date, scenario_label="benchmark", bug=bug)

        ground_truth.append({
            "scenario_id": scenario_id,
            "run_date": run_date.isoformat(),
            "bug_type": bug_type,
            "difficulty": difficulty,
            "params": bug.params,
            "staging_row_count": n_rows,
            "mechanism": CATALOG[bug_type],
        })
        print(f"  {scenario_id}: {bug_type:24s} ({difficulty:8s}) on {run_date} -- {n_rows} rows")

    conn.close()

    FIXTURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURES_PATH.write_text(json.dumps(ground_truth, indent=2), encoding="utf-8")
    print(f"\nWrote ground truth for {len(ground_truth)} scenarios to {FIXTURES_PATH}")


if __name__ == "__main__":
    main()
