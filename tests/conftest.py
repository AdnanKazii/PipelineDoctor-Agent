import datetime as dt
import random

import pytest

from src.pipeline.db import get_connection
from src.pipeline.schema import init_schema
from src.pipeline.transform import CLEAN, build_run

RUN_DATE = "2024-01-15"


@pytest.fixture
def conn():
    """An in-memory DuckDB with the pipeline schema and a small hand-crafted
    fixture dataset — no dependency on the real Olist CSVs, so this runs fast
    and works in CI with no data present."""
    c = get_connection(":memory:")
    init_schema(c)

    c.execute(
        "INSERT INTO src_orders VALUES "
        "('o1','c1','delivered', TIMESTAMP '2024-01-15 10:00:00', NULL, NULL, NULL, NULL),"
        "('o2','c2','delivered', TIMESTAMP '2024-01-15 11:00:00', NULL, NULL, NULL, NULL),"
        "('o3','c3','delivered', TIMESTAMP '2024-01-15 23:30:00', NULL, NULL, NULL, NULL),"
        "('o4','c4','delivered', TIMESTAMP '2024-01-16 00:30:00', NULL, NULL, NULL, NULL)"
    )
    c.execute(
        "INSERT INTO src_order_items VALUES "
        "('o1', 1, 'p1', 's1', NULL, 100.0, 10.0),"
        "('o2', 1, 'p2', 's2', NULL, 50.0, 5.0),"
        "('o3', 1, 'p1', 's1', NULL, 80.0, 8.0),"
        "('o4', 1, 'p2', 's2', NULL, 60.0, 6.0)"
    )
    c.execute(
        "INSERT INTO src_products VALUES "
        "('p1', 'moveis_decoracao'),"
        "('p2', 'cama_mesa_banho')"
    )
    c.execute(
        "INSERT INTO src_sellers VALUES "
        "('s1', 11000, 'sao paulo', 'SP'),"
        "('s2', 20000, 'rio', 'RJ')"
    )
    c.execute(
        "INSERT INTO src_category_translation VALUES "
        "('moveis_decoracao', 'furniture_decor'),"
        "('cama_mesa_banho', 'bed_bath_table')"
    )
    return c


SELLERS = [("s1", "SP"), ("s2", "SP"), ("s3", "RJ"), ("s4", "MG"), ("s5", "BA")]
CATEGORIES = [("moveis_decoracao", "furniture_decor"), ("cama_mesa_banho", "bed_bath_table"),
              ("informatica_acessorios", "computers_accessories")]
BASELINE_DATES = [dt.date(2024, 2, d) for d in range(1, 9)]  # 8 clean baseline days


@pytest.fixture
def rich_conn():
    """A larger synthetic dataset with several clean baseline runs already
    built, for tools that compare a suspect run against 'what normal looks
    like' (null_rate, value_distribution_diff)."""
    c = get_connection(":memory:")
    init_schema(c)

    c.executemany(
        "INSERT INTO src_sellers VALUES (?, ?, ?, ?)",
        [(sid, 10000, "city", state) for sid, state in SELLERS],
    )
    c.executemany(
        "INSERT INTO src_category_translation VALUES (?, ?)",
        CATEGORIES,
    )
    products = [(f"p{i}", CATEGORIES[i % len(CATEGORIES)][0]) for i in range(len(CATEGORIES) * 3)]
    c.executemany("INSERT INTO src_products VALUES (?, ?)", products)

    rng = random.Random(42)
    order_rows, item_rows = [], []
    oid = 0
    for d in BASELINE_DATES:
        for _ in range(25):
            oid += 1
            order_id = f"bo{oid}"
            ts = dt.datetime.combine(d, dt.time(rng.randint(1, 22), rng.randint(0, 59)))
            order_rows.append((order_id, "cust", "delivered", ts, None, None, None, None))
            product = rng.choice(products)
            seller = rng.choice(SELLERS)
            price = round(rng.uniform(20, 200), 2)
            freight = round(rng.uniform(5, 25), 2)
            item_rows.append((order_id, 1, product[0], seller[0], None, price, freight))

    c.executemany("INSERT INTO src_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)", order_rows)
    c.executemany("INSERT INTO src_order_items VALUES (?, ?, ?, ?, ?, ?, ?)", item_rows)

    for d in BASELINE_DATES:
        build_run(c, f"clean_{d.isoformat()}", d, scenario_label="baseline", bug=CLEAN)

    return c
