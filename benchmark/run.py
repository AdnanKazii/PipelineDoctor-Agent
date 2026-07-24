"""Runs the agent against every benchmark scenario and scores the results.

Usage:
    python -m benchmark.run            # full 27-scenario benchmark
    python -m benchmark.run --smoke    # first 5 scenarios only (what CI runs)
"""

import argparse
import json
import time
from pathlib import Path

from src.agent.loop import AgentRun, AgentRunResult
from src.pipeline.db import get_connection
from .scorer import ScenarioScore, score_scenario, summarize

FIXTURES_PATH = Path(__file__).parent / "fixtures" / "scenarios.json"
RESULTS_DIR = Path(__file__).parent / "results"


def run_benchmark(smoke: bool = False) -> dict:
    scenarios = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
    if smoke:
        scenarios = scenarios[:5]

    conn = get_connection(read_only=True)
    scores: list[ScenarioScore] = []

    for truth in scenarios:
        agent = AgentRun(conn)
        start = time.monotonic()
        error = None
        try:
            result = agent.diagnose(truth["scenario_id"])
        except Exception as exc:  # noqa: BLE001 - recorded as a scenario failure, not fatal to the run
            result = AgentRunResult(run_id=truth["scenario_id"], diagnosis=None)
            error = str(exc)
        latency_s = time.monotonic() - start

        score = score_scenario(truth, result, latency_s, error=error)
        scores.append(score)
        status = "ERROR" if error else ("OK" if score.classification_correct else "MISS")
        print(f"{truth['scenario_id']}: truth={truth['bug_type']:24s} guess={str(score.guess_bug_type):24s} {status}")

    conn.close()

    summary = summarize(scores)
    _write_results(scores, summary, smoke)
    return summary


def _write_results(scores: list[ScenarioScore], summary: dict, smoke: bool) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "_smoke" if smoke else ""

    (RESULTS_DIR / f"results{suffix}.json").write_text(json.dumps({
        "summary": summary,
        "scores": [vars(s) for s in scores],
    }, indent=2, default=str), encoding="utf-8")

    lines = [
        f"# Benchmark results{' (smoke subset)' if smoke else ''}",
        "",
        f"- Scenarios: {summary['n_scenarios']} ({summary['n_errored']} errored)",
        f"- Detection accuracy (healthy vs. defective): {_pct(summary['detection_accuracy'])}",
        f"- Classification accuracy (exact bug type): {_pct(summary['classification_accuracy'])}",
        f"- False positive rate (clean runs flagged as buggy): {_pct(summary['false_positive_rate'])}",
        f"- False negative rate (buggy runs called clean): {_pct(summary['false_negative_rate'])}",
        f"- Avg tool calls / scenario: {_num(summary['avg_tool_calls'])}",
        f"- Avg supporting numbers verified: {_pct(summary['avg_verified_fraction'])}",
        f"- Avg latency / scenario: {_num(summary['avg_latency_s'])}s",
        f"- Total estimated cost: ${summary['total_estimated_cost_usd']:.4f}"
        f" (${summary['avg_estimated_cost_usd'] or 0:.4f}/scenario)",
        "",
        "## By bug type",
        "",
        "| bug_type | n | classification accuracy |",
        "|---|---|---|",
    ]
    for bug_type, stats in summary["by_bug_type"].items():
        lines.append(f"| {bug_type} | {stats['n']} | {_pct(stats['classification_accuracy'])} |")

    lines += ["", "## By difficulty", "", "| difficulty | n | classification accuracy |", "|---|---|---|"]
    for difficulty, stats in summary["by_difficulty"].items():
        lines.append(f"| {difficulty} | {stats['n']} | {_pct(stats['classification_accuracy'])} |")

    lines += ["", "## Per-scenario", "", "| scenario | truth | guess | correct | tool calls | cost |", "|---|---|---|---|---|---|"]
    for s in scores:
        mark = "error" if s.error else ("✓" if s.classification_correct else "✗")
        lines.append(
            f"| {s.scenario_id} | {s.truth_bug_type} | {s.guess_bug_type} | {mark} | "
            f"{s.tool_call_count} | ${s.estimated_cost_usd:.4f} |"
        )

    (RESULTS_DIR / f"RESULTS{suffix}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _num(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.2f}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    summary = run_benchmark(smoke=args.smoke)
    print(json.dumps(summary, indent=2, default=str))
