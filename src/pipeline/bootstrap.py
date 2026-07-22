"""Loads the Olist source data and builds a clean baseline run for a spread of
dates. These clean runs are what the diagnostic tools use as a "what normal
looks like" baseline when investigating a suspect run.

Usage: python -m src.pipeline.bootstrap
"""

import datetime as dt

from .db import get_connection
from .loader import load_sources
from .transform import CLEAN, build_run

MIN_DAILY_ORDERS = 80
NUM_BASELINE_DATES = 40


def pick_baseline_dates(conn, limit: int = NUM_BASELINE_DATES) -> list[dt.date]:
    rows = conn.execute(
        """
        SELECT CAST(order_purchase_timestamp AS DATE) AS d, count(*) AS n
        FROM src_orders
        GROUP BY d
        HAVING n >= ?
        ORDER BY d
        """,
        [MIN_DAILY_ORDERS],
    ).fetchall()
    dates = [r[0] for r in rows]
    if len(dates) <= limit:
        return dates
    step = len(dates) / limit
    return [dates[int(i * step)] for i in range(limit)]


def main() -> None:
    conn = get_connection()
    print("Loading source CSVs...")
    load_sources(conn)

    dates = pick_baseline_dates(conn)
    print(f"Building {len(dates)} clean baseline runs...")
    for d in dates:
        run_id = f"clean_{d.isoformat()}"
        n = build_run(conn, run_id, d, scenario_label="baseline", bug=CLEAN)
        print(f"  {run_id}: {n} staging rows")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
