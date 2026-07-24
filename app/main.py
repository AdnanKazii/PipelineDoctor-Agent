import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import duckdb
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from src.agent.loop import AgentRun
from src.agent.tools.schema_tools import get_run_manifest
from .rate_limit import RateLimiter

APP_DIR = Path(__file__).parent
DB_PATH = os.environ.get("PIPELINE_DB_PATH", "data/pipeline.duckdb")

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not Path(DB_PATH).exists():
        raise RuntimeError(
            f"No pipeline database at {DB_PATH}. Run `python -m src.pipeline.bootstrap` first."
        )
    state["conn"] = duckdb.connect(DB_PATH, read_only=True)
    yield
    state["conn"].close()


app = FastAPI(title="Pipeline Doctor Agent", lifespan=lifespan)
app.add_middleware(RateLimiter)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")


class DiagnoseRequest(BaseModel):
    run_id: str


def _conn() -> duckdb.DuckDBPyConnection:
    return state["conn"]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/runs")
def list_runs():
    """Runs available to investigate. Deliberately excludes bug_type -- that's
    ground truth, not something a real user would have on hand."""
    return get_run_manifest(_conn())


@app.post("/diagnose")
def diagnose(req: DiagnoseRequest):
    agent = AgentRun(_conn())
    try:
        result = agent.diagnose(req.run_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Agent run failed: {exc}") from exc

    return {
        "run_id": result.run_id,
        "diagnosis": result.diagnosis.model_dump() if result.diagnosis else None,
        "trace": result.trace,
        "iterations": result.iterations,
        "usage": result.usage,
    }


@app.get("/diagnose/stream")
def diagnose_stream(run_id: str):
    agent = AgentRun(_conn())

    def event_source():
        try:
            for event in agent.diagnose_stream(run_id):
                yield f"data: {json.dumps(event, default=str)}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")
