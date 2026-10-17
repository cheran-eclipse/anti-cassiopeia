"""
Algorithms / data domain adapter — ML POV.

Verifies claims about a dataset by actually re-computing the statistic
from the dataset, not by trusting a reported number. No pandas dependency
— stdlib `csv` + `statistics` only, kept deliberately small.

STATUS: real, offline, tested. No network or external service involved —
this is the one domain that needed neither an API key nor a live
retrieval pipeline to be genuinely real, so it is.

Claim contract (via Claim.context — claim.text stays human-readable,
this is what gather_evidence actually reads):
    context = {
        "dataset_path": str,         # CSV file, relative to CWD or absolute
        "column": str,                # header name, numeric column
        "stat": "mean" | "min" | "max" | "stdev",
        "expected_value": float,
        "tolerance": float = 1e-6,    # absolute tolerance for "supports"
    }

A claim missing any required context key, a missing file, a non-numeric
column, or a bad `stat` name all produce NO evidence plus a specific,
named reason via describe_gap() — never a crash, never a silent zero.
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path

from anticassiopeia.core.domain import DomainAdapter
from anticassiopeia.core.verdict import Claim, Evidence

_STAT_FUNCS = {
    "mean": statistics.mean,
    "min": min,
    "max": max,
    "stdev": statistics.stdev,
}


class MLDataAdapter(DomainAdapter):
    domain_name = "ml_data"
    implemented = True

    async def gather_evidence(self, claim: Claim) -> list[Evidence]:
        ctx = claim.context
        gap = self._check(ctx)
        if gap is not None:
            return []

        path = Path(ctx["dataset_path"])
        column = ctx["column"]
        stat_name = ctx["stat"]
        values, row_count, bad_rows = self._read_column(path, column)
        computed = _STAT_FUNCS[stat_name](values)
        expected = float(ctx["expected_value"])
        tolerance = float(ctx.get("tolerance", 1e-6))
        diff = abs(computed - expected)

        locator = f"{path}:column={column},rows={row_count}" + (f",skipped_non_numeric={bad_rows}" if bad_rows else "")
        snippet = (
            f"Re-computed {stat_name}({column}) = {computed!r} over {row_count} row(s) "
            f"(expected {expected!r}, tolerance {tolerance!r}, diff {diff!r})."
        )

        if diff <= tolerance:
            stance = "supports"
            trust = 0.95  # directly re-computed from the actual file, not reported
        else:
            stance = "contradicts"
            trust = 0.95

        return [Evidence(source=str(path), snippet=snippet, stance=stance, trust=trust, locator=locator)]

    def describe_gap(self, claim: Claim, evidence: list[Evidence]) -> list[str]:
        if evidence:
            return super().describe_gap(claim, evidence)
        gap = self._check(claim.context)
        return [gap] if gap else ["No computed/re-run evidence found for this metric or statistical claim."]

    @staticmethod
    def _check(ctx: dict) -> str | None:
        """Re-derives, statelessly, why gather_evidence would return no evidence for
        this context — used by both gather_evidence (to short-circuit) and
        describe_gap (to explain). Deliberately no shared mutable state between the
        two, so concurrent calls on one adapter instance can't cross-contaminate
        their gap reasons."""
        required = {"dataset_path", "column", "stat", "expected_value"}
        missing_keys = required - ctx.keys()
        if missing_keys:
            return f"Claim is missing required context key(s): {sorted(missing_keys)}."

        path = Path(ctx["dataset_path"])
        if not path.is_file():
            return f"Dataset file not found at '{path}' — cannot compute, cannot guess."

        stat_name = ctx["stat"]
        if stat_name not in _STAT_FUNCS:
            return f"Unknown stat '{stat_name}'. Supported: {sorted(_STAT_FUNCS)}."

        column = ctx["column"]
        values, _, _ = MLDataAdapter._read_column(path, column)
        if values is None:
            return f"Column '{column}' not found in '{path}'."
        if not values:
            return f"Column '{column}' in '{path}' has no numeric values to compute '{stat_name}' from."
        return None

    @staticmethod
    def _read_column(path: Path, column: str) -> tuple[list[float] | None, int, int]:
        """Returns (values, total_row_count, non_numeric_rows_skipped). values is None
        if the column header doesn't exist at all."""
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or column not in reader.fieldnames:
                return None, 0, 0
            values: list[float] = []
            row_count = 0
            bad_rows = 0
            for row in reader:
                row_count += 1
                raw = row.get(column, "")
                try:
                    values.append(float(raw))
                except (TypeError, ValueError):
                    bad_rows += 1
            return values, row_count, bad_rows
