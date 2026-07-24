from typing import Literal

from pydantic import BaseModel, Field

from src.pipeline.bugs import CATALOG

BugTypeGuess = Literal[
    "clean", "row_filter_bug", "join_fanout_bug", "schema_drift_bug",
    "stale_reference_bug", "null_coalesce_bug", "currency_unit_bug",
    "timezone_bucketing_bug", "other",
]
assert set(BugTypeGuess.__args__) - {"other"} == set(CATALOG.keys())


class SupportingNumber(BaseModel):
    label: str = Field(description="What this number represents, e.g. 'staging row count'.")
    value: float
    source_tool: str = Field(description="Which tool produced this number.")
    verified: bool = Field(description="Whether verify_finding was called to confirm this exact value.")


class DiagnosisResult(BaseModel):
    root_cause_diagnosis: str = Field(description="Plain-English explanation of what's wrong (or that nothing is).")
    bug_type_guess: BugTypeGuess
    affected_scope: str = Field(description="Which tables/columns/rows are affected, and the date/run in question.")
    supporting_numbers: list[SupportingNumber] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list, description="Concrete observations that support the diagnosis.")
    confidence: float = Field(ge=0, le=1)
    caveats: list[str] = Field(default_factory=list)
