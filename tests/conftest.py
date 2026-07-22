import pytest

from src.pipeline.db import get_connection
from src.pipeline.schema import init_schema

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
