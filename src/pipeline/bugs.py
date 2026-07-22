from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BugSpec:
    """A single injected pipeline defect. `params` carries the specifics
    (which state/category/seller is affected) so the same bug_type can be
    instantiated differently across benchmark scenarios."""

    bug_type: str
    params: dict[str, Any] = field(default_factory=dict)


# Human-readable catalog used by the README/benchmark docs — the *mechanism* of
# each bug, not which specific run it was injected into (that's per-scenario ground truth).
CATALOG: dict[str, str] = {
    "clean": "No defect. Staging/facts are built straightforwardly from source.",
    "row_filter_bug": (
        "The staging join carries an accidental filter that silently drops every "
        "order item from one seller_state, e.g. a leftover debug WHERE clause."
    ),
    "join_fanout_bug": (
        "The category-translation lookup has a duplicate row for one category, so "
        "the join fans out and every item in that category is double-counted."
    ),
    "schema_drift_bug": (
        "For one category, the upstream category name arrives with an unexpected "
        "format (e.g. trailing whitespace) that breaks the translation join key, "
        "so category_english lands NULL for exactly that category's items."
    ),
    "stale_reference_bug": (
        "The category-translation reference used by this run is a stale snapshot "
        "missing a couple of categories, so those categories' items get no English "
        "name."
    ),
    "null_coalesce_bug": (
        "One seller's item prices arrive NULL (an upstream data-quality gap), and "
        "the facts aggregation silently COALESCEs price to 0 instead of excluding "
        "or flagging those rows, understating revenue without erroring."
    ),
    "currency_unit_bug": (
        "Freight values for one seller_state are systematically scaled by the wrong "
        "unit factor (e.g. cents vs. dollars), skewing avg_freight for that state."
    ),
    "timezone_bucketing_bug": (
        "The staging date filter buckets orders using a shifted local-time boundary "
        "instead of the correct one, so a slice of orders near midnight land in the "
        "wrong day's run."
    ),
}
