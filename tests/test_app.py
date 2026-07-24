import datetime as dt

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.rate_limit import RateLimiter
from src.pipeline.db import get_connection
from src.pipeline.schema import init_schema
from src.pipeline.transform import CLEAN, build_run


def test_health_and_runs_endpoints(tmp_path, monkeypatch):
    db_path = tmp_path / "pipeline.duckdb"
    conn = get_connection(db_path)
    init_schema(conn)
    conn.execute(
        "INSERT INTO src_orders VALUES ('o1','c1','delivered', TIMESTAMP '2024-01-15 10:00:00', NULL, NULL, NULL, NULL)"
    )
    conn.execute("INSERT INTO src_order_items VALUES ('o1', 1, 'p1', 's1', NULL, 100.0, 10.0)")
    conn.execute("INSERT INTO src_products VALUES ('p1', 'moveis_decoracao')")
    conn.execute("INSERT INTO src_sellers VALUES ('s1', 11000, 'sao paulo', 'SP')")
    conn.execute("INSERT INTO src_category_translation VALUES ('moveis_decoracao', 'furniture_decor')")
    build_run(conn, "clean_2024-01-15", dt.date(2024, 1, 15), scenario_label="baseline", bug=CLEAN)
    conn.close()

    monkeypatch.setenv("PIPELINE_DB_PATH", str(db_path))
    from app.main import app  # imported after env var is set so lifespan picks it up

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

        runs = client.get("/runs").json()
        assert runs["runs"][0]["run_id"] == "clean_2024-01-15"
        assert "bug_type" not in runs["runs"][0]

        index = client.get("/")
        assert index.status_code == 200
        assert "Pipeline Doctor Agent" in index.text


def test_rate_limiter_returns_429_after_limit():
    app = FastAPI()
    app.add_middleware(RateLimiter, per_hour=2, per_day=10)

    @app.post("/diagnose")
    def diagnose():
        return {"ok": True}

    client = TestClient(app)
    assert client.post("/diagnose").status_code == 200
    assert client.post("/diagnose").status_code == 200
    third = client.post("/diagnose")
    assert third.status_code == 429
