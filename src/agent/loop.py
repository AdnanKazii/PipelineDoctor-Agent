import os
from collections.abc import Iterator
from dataclasses import dataclass, field

import duckdb
from anthropic import Anthropic

from .prompts import SYSTEM_PROMPT
from .schemas import DiagnosisResult
from .tool_defs import build_tools

DEFAULT_MODEL = os.environ.get("AGENT_MODEL", "claude-sonnet-5")
DEFAULT_MAX_ITERATIONS = 12


@dataclass
class AgentRunResult:
    run_id: str
    diagnosis: DiagnosisResult | None
    trace: list[dict] = field(default_factory=list)
    iterations: int = 0
    usage: dict = field(default_factory=dict)


class AgentRun:
    """One shared investigation loop used by the API endpoint, the benchmark
    harness, and tests, so the benchmark measures exactly what production runs.
    Tool use and the final structured diagnosis happen in a single tool_runner
    loop -- the SDK validates the model's final (tool-less) turn against
    DiagnosisResult directly, so no separate synthesis call is needed."""

    def __init__(self, conn: duckdb.DuckDBPyConnection, client: Anthropic | None = None, model: str = DEFAULT_MODEL):
        self.conn = conn
        self.client = client or Anthropic()
        self.model = model

    def diagnose_stream(self, run_id: str, max_iterations: int = DEFAULT_MAX_ITERATIONS) -> Iterator[dict]:
        """Yields {"type": "tool_call", ...} events as the investigation
        progresses, then a final {"type": "done", ...} event. A tool's result
        lands in `trace` while the *next* message is being produced (the
        runner executes tool calls between yields), so diffing `trace` against
        what we've already emitted, each time we receive a message, correctly
        streams every call as soon as it's available."""
        trace: list[dict] = []
        tools = build_tools(self.conn, trace)

        runner = self.client.beta.messages.tool_runner(
            model=self.model,
            max_tokens=4096,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{
                "role": "user",
                "content": f"Investigate pipeline run_id='{run_id}' and produce a diagnosis.",
            }],
            tools=tools,
            output_format=DiagnosisResult,
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={"effort": "high"},
            max_iterations=max_iterations,
        )

        final_message = None
        iterations = 0
        emitted = 0
        usage = {
            "input_tokens": 0, "output_tokens": 0,
            "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
        }
        for message in runner:
            final_message = message
            iterations += 1
            u = message.usage
            usage["input_tokens"] += u.input_tokens
            usage["output_tokens"] += u.output_tokens
            usage["cache_read_input_tokens"] += u.cache_read_input_tokens or 0
            usage["cache_creation_input_tokens"] += u.cache_creation_input_tokens or 0

            for entry in trace[emitted:]:
                yield {"type": "tool_call", **entry}
            emitted = len(trace)

        for entry in trace[emitted:]:
            yield {"type": "tool_call", **entry}

        diagnosis = final_message.parsed_output if final_message is not None else None
        yield {
            "type": "done",
            "run_id": run_id,
            "diagnosis": diagnosis.model_dump() if diagnosis else None,
            "iterations": iterations,
            "usage": usage,
        }

    def diagnose(self, run_id: str, max_iterations: int = DEFAULT_MAX_ITERATIONS) -> AgentRunResult:
        trace: list[dict] = []
        done: dict | None = None
        for event in self.diagnose_stream(run_id, max_iterations=max_iterations):
            if event["type"] == "tool_call":
                trace.append({k: v for k, v in event.items() if k != "type"})
            else:
                done = event

        return AgentRunResult(
            run_id=run_id,
            diagnosis=DiagnosisResult.model_validate(done["diagnosis"]) if done and done["diagnosis"] else None,
            trace=trace,
            iterations=done["iterations"] if done else 0,
            usage=done["usage"] if done else {},
        )
