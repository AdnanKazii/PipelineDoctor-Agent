from dataclasses import dataclass, field
from statistics import mean

from src.agent.loop import AgentRunResult

# Sonnet 5 intro pricing: $2/$10 per MTok input/output. Cache read/write
# multipliers follow Anthropic's standard cache economics (~0.1x / ~1.25x base
# input price). This is an estimate for benchmark reporting, not a billing figure.
PRICE_PER_MTOK = {"input": 2.0, "output": 10.0, "cache_read": 0.2, "cache_write": 2.5}


def estimate_cost_usd(usage: dict) -> float:
    return (
        usage.get("input_tokens", 0) * PRICE_PER_MTOK["input"]
        + usage.get("output_tokens", 0) * PRICE_PER_MTOK["output"]
        + usage.get("cache_read_input_tokens", 0) * PRICE_PER_MTOK["cache_read"]
        + usage.get("cache_creation_input_tokens", 0) * PRICE_PER_MTOK["cache_write"]
    ) / 1_000_000


@dataclass
class ScenarioScore:
    scenario_id: str
    truth_bug_type: str
    difficulty: str
    guess_bug_type: str | None
    detection_correct: bool
    classification_correct: bool
    iterations: int
    tool_call_count: int
    verified_fraction: float | None
    usage: dict = field(default_factory=dict)
    estimated_cost_usd: float = 0.0
    latency_s: float = 0.0
    error: str | None = None


def score_scenario(truth: dict, result: AgentRunResult, latency_s: float, error: str | None = None) -> ScenarioScore:
    diagnosis = result.diagnosis
    guess = diagnosis.bug_type_guess if diagnosis else None
    truth_bug = truth["bug_type"]

    detection_correct = guess is not None and (guess == "clean") == (truth_bug == "clean")
    classification_correct = guess == truth_bug

    numbers = diagnosis.supporting_numbers if diagnosis else []
    verified_fraction = (sum(1 for n in numbers if n.verified) / len(numbers)) if numbers else None

    return ScenarioScore(
        scenario_id=truth["scenario_id"],
        truth_bug_type=truth_bug,
        difficulty=truth["difficulty"],
        guess_bug_type=guess,
        detection_correct=detection_correct,
        classification_correct=classification_correct,
        iterations=result.iterations,
        tool_call_count=len(result.trace),
        verified_fraction=verified_fraction,
        usage=result.usage,
        estimated_cost_usd=estimate_cost_usd(result.usage),
        latency_s=latency_s,
        error=error,
    )


def summarize(scores: list[ScenarioScore]) -> dict:
    valid = [s for s in scores if s.error is None]
    clean_truth = [s for s in valid if s.truth_bug_type == "clean"]
    bugged_truth = [s for s in valid if s.truth_bug_type != "clean"]
    verified_fracs = [s.verified_fraction for s in valid if s.verified_fraction is not None]

    by_bug_type: dict[str, dict] = {}
    for bug_type in sorted({s.truth_bug_type for s in valid}):
        subset = [s for s in valid if s.truth_bug_type == bug_type]
        by_bug_type[bug_type] = {
            "n": len(subset),
            "classification_accuracy": mean(s.classification_correct for s in subset),
        }

    by_difficulty: dict[str, dict] = {}
    for difficulty in sorted({s.difficulty for s in valid}):
        subset = [s for s in valid if s.difficulty == difficulty]
        by_difficulty[difficulty] = {
            "n": len(subset),
            "classification_accuracy": mean(s.classification_correct for s in subset),
        }

    return {
        "n_scenarios": len(scores),
        "n_errored": len(scores) - len(valid),
        "detection_accuracy": mean(s.detection_correct for s in valid) if valid else None,
        "classification_accuracy": mean(s.classification_correct for s in valid) if valid else None,
        "false_positive_rate": (
            mean(s.guess_bug_type != "clean" for s in clean_truth) if clean_truth else None
        ),
        "false_negative_rate": (
            mean(s.guess_bug_type == "clean" for s in bugged_truth) if bugged_truth else None
        ),
        "avg_tool_calls": mean(s.tool_call_count for s in valid) if valid else None,
        "avg_iterations": mean(s.iterations for s in valid) if valid else None,
        "avg_verified_fraction": mean(verified_fracs) if verified_fracs else None,
        "avg_latency_s": mean(s.latency_s for s in valid) if valid else None,
        "total_estimated_cost_usd": sum(s.estimated_cost_usd for s in valid),
        "avg_estimated_cost_usd": mean(s.estimated_cost_usd for s in valid) if valid else None,
        "by_bug_type": by_bug_type,
        "by_difficulty": by_difficulty,
    }
