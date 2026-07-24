
import pytest

from benchmark.run import run_benchmark
from benchmark.scorer import estimate_cost_usd, score_scenario, summarize
from src.agent.loop import AgentRun, AgentRunResult
from src.agent.schemas import DiagnosisResult


def _result(bug_type_guess, verified=True):
    diagnosis = DiagnosisResult(
        root_cause_diagnosis="x", bug_type_guess=bug_type_guess, affected_scope="x",
        supporting_numbers=[{"label": "n", "value": 1.0, "source_tool": "row_count_diff", "verified": verified}],
        evidence=["e"], confidence=0.8, caveats=[],
    )
    return AgentRunResult(
        run_id="s", diagnosis=diagnosis, trace=[{"tool": "row_count_diff"}], iterations=2,
        usage={"input_tokens": 1000, "output_tokens": 100, "cache_read_input_tokens": 500, "cache_creation_input_tokens": 0},
    )


def test_score_scenario_correct_and_incorrect():
    truth = {"scenario_id": "scenario_001", "bug_type": "row_filter_bug", "difficulty": "dominant"}
    correct = score_scenario(truth, _result("row_filter_bug"), latency_s=1.0)
    assert correct.detection_correct is True
    assert correct.classification_correct is True

    wrong = score_scenario(truth, _result("clean"), latency_s=1.0)
    assert wrong.detection_correct is False
    assert wrong.classification_correct is False


def test_score_scenario_handles_no_diagnosis():
    truth = {"scenario_id": "scenario_001", "bug_type": "clean", "difficulty": "n/a"}
    empty = AgentRunResult(run_id="s", diagnosis=None)
    score = score_scenario(truth, empty, latency_s=0.5, error="boom")
    assert score.guess_bug_type is None
    assert score.detection_correct is False
    assert score.error == "boom"


def test_estimate_cost_is_nonzero_for_nonzero_usage():
    cost = estimate_cost_usd({"input_tokens": 1_000_000, "output_tokens": 1_000_000})
    assert cost == pytest.approx(12.0)


def test_summarize_computes_false_positive_and_negative_rates():
    truths = [
        {"scenario_id": "a", "bug_type": "clean", "difficulty": "n/a"},
        {"scenario_id": "b", "bug_type": "row_filter_bug", "difficulty": "dominant"},
    ]
    scores = [
        score_scenario(truths[0], _result("row_filter_bug"), 1.0),  # false positive: clean flagged as buggy
        score_scenario(truths[1], _result("clean"), 1.0),  # false negative: bug called clean
    ]
    summary = summarize(scores)
    assert summary["false_positive_rate"] == 1.0
    assert summary["false_negative_rate"] == 1.0
    assert summary["classification_accuracy"] == 0.0


def test_run_benchmark_smoke_with_mocked_agent(tmp_path, monkeypatch):
    def fake_diagnose(self, run_id, max_iterations=12):
        return _result("row_filter_bug" if "001" in run_id else "clean")

    # diagnose() is fully mocked and never touches the network or the DB
    # connection, but AgentRun.__init__ still constructs a real Anthropic
    # client if none is passed, which requires *a* key to be present.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-dummy")
    monkeypatch.setattr(AgentRun, "diagnose", fake_diagnose)
    monkeypatch.setattr("benchmark.run.RESULTS_DIR", tmp_path)

    import benchmark.run as run_module
    monkeypatch.setattr(run_module, "get_connection", lambda *a, **k: type("C", (), {"close": lambda self: None})())

    summary = run_benchmark(smoke=True)
    assert summary["n_scenarios"] == 5
    assert (tmp_path / "results_smoke.json").exists()
    assert (tmp_path / "RESULTS_smoke.md").exists()
