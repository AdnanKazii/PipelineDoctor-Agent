from types import SimpleNamespace
from unittest.mock import MagicMock

from src.agent.loop import AgentRun
from src.agent.schemas import DiagnosisResult


def _fake_usage(input_tokens, output_tokens, cache_read=0, cache_creation=0):
    return SimpleNamespace(
        input_tokens=input_tokens, output_tokens=output_tokens,
        cache_read_input_tokens=cache_read, cache_creation_input_tokens=cache_creation,
    )


def test_diagnose_aggregates_usage_and_returns_parsed_output(conn):
    diagnosis = DiagnosisResult(
        root_cause_diagnosis="Row-filter bug excluding SP sellers.",
        bug_type_guess="row_filter_bug",
        affected_scope="stg_order_items_enriched, seller_state=SP, run r1",
        supporting_numbers=[],
        evidence=["staging row count is far below the independent source count"],
        confidence=0.9,
        caveats=[],
    )
    messages = [
        SimpleNamespace(usage=_fake_usage(1000, 50, cache_read=0, cache_creation=1000), parsed_output=None),
        SimpleNamespace(usage=_fake_usage(1200, 30, cache_read=1000, cache_creation=0), parsed_output=None),
        SimpleNamespace(usage=_fake_usage(1300, 200, cache_read=1200, cache_creation=0), parsed_output=diagnosis),
    ]

    fake_client = MagicMock()
    fake_client.beta.messages.tool_runner.return_value = iter(messages)

    agent = AgentRun(conn, client=fake_client, model="claude-sonnet-5")
    result = agent.diagnose("r1")

    assert result.iterations == 3
    assert result.diagnosis == diagnosis
    assert result.usage["input_tokens"] == 1000 + 1200 + 1300
    assert result.usage["output_tokens"] == 50 + 30 + 200
    assert result.usage["cache_read_input_tokens"] == 0 + 1000 + 1200

    call_kwargs = fake_client.beta.messages.tool_runner.call_args.kwargs
    assert call_kwargs["model"] == "claude-sonnet-5"
    assert call_kwargs["output_format"] is DiagnosisResult
    assert "r1" in call_kwargs["messages"][0]["content"]


def test_diagnose_returns_none_diagnosis_if_no_messages(conn):
    fake_client = MagicMock()
    fake_client.beta.messages.tool_runner.return_value = iter([])

    agent = AgentRun(conn, client=fake_client)
    result = agent.diagnose("r1")

    assert result.diagnosis is None
    assert result.iterations == 0
