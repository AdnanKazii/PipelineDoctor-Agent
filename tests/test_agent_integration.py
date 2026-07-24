import datetime as dt
import os

import pytest

from src.agent.loop import AgentRun
from src.pipeline.bugs import BugSpec
from src.pipeline.transform import build_run

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"), reason="requires a real ANTHROPIC_API_KEY"
)


def test_agent_diagnoses_a_real_injected_bug_end_to_end(rich_conn):
    """One real call to the live Claude API, skipped unless a key is present.
    Everything else in the suite runs against mocked responses."""
    bug = BugSpec("row_filter_bug", {"excluded_seller_state": "SP"})
    build_run(rich_conn, "integration_suspect", dt.date(2024, 2, 1), bug=bug)

    agent = AgentRun(rich_conn)
    result = agent.diagnose("integration_suspect")

    assert result.diagnosis is not None
    assert result.diagnosis.bug_type_guess in {"row_filter_bug", "other"}
    assert result.iterations > 0
