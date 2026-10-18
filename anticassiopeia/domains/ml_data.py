"""
Algorithms / data domain adapter — ML POV.

Verifies claims about a dataset by actually re-computing the statistic
from the dataset, not by trusting a reported number. No pandas dependency
— stdlib `csv` + `statistics` only, kept deliberately small. See
docs/DESIGN.md §5 for why this adapter stays outside the shared
`retrieval/` package entirely: there is no "right passage" to search for
here, just a computation to run over every row.

STATUS: real, offline, tested. No network or external service involved.

GROWTH (this pass): median, p25/p75 percentiles, and correlation between
two columns — all via stdlib `statistics` (`median()`, `quantiles()`,
and `correlation()`, the last added in Python 3.10; this project already
requires >=3.11, so NO new dependency was needed for any of this).
Multi-file datasets (one claim checked against rows split across more
than one CSV). Real AND-semantics claim decomposition for compound
statistical claims ("mean is X AND stdev is Y").

FIXED BUG, found while adding stdev's new siblings: `stdev`, and now
`p25`/`p75`/`correlation`, all raise `statistics.StatisticsError` on too
few data points (stdev needs >=2, quantiles/correlation effectively the
same) — the PRE-EXISTING `_check()` only ever validated "not empty", not
"enough points for this specific stat", so a single-numeric-value column
with `stat: "stdev"` would have crashed `gather_evidence()` with an
uncaught exception instead of a named gap. Fixed by checking each stat's
real minimum sample size before computing, not after.

Claim contract (via Claim.context — claim.text stays human-readable,
this is what gather_evidence actually reads). TWO shapes:

1. Single statistic (original shape, extended):
    context = {
        "dataset_path": str | list[str],   # one CSV, or several sharing a schema
        "column": str,                      # header name, numeric column
        "stat": "mean" | "min" | "max" | "stdev" | "median" | "p25" | "p75" | "correlation",
        "column_b": str,                    # required only for stat == "correlation"
        "expected_value": float,
        "tolerance": float = 1e-6,          # absolute tolerance for "supports"
    }
   `dataset_path` as a list concatenates rows from every file (in order)
   before computing — a dataset genuinely split across shards is checked
   as one dataset, not shard by shard. Every file must contain the
   required column(s); one shard missing a column is a specific, named
   mismatch, not silently skipped.

2. Compound claim (new — real AND semantics, enforced HERE, not left to
   core/engine.py's generic trust-weighted sum):
    context = {
        "dataset_path": ..., "column": ...,   # optional shared defaults
        "checks": [
            {"stat": "mean", "expected_value": 5.0, "tolerance": 0.01},
            {"stat": "stdev", "expected_value": 0.02, "tolerance": 0.005},
            ...  # each entry may override dataset_path/column/column_b/tolerance
        ],
    }
   A compound claim is CONFIRMED only if EVERY sub-check's computed value
   matches; if even one genuinely computable sub-check disagrees, the
   whole claim is CONTRADICTED (not averaged against the ones that DID
   match — "A and B" is false if B is false, full stop), and the gap
   message names exactly which sub-check(s) failed and by how much. A
   sub-check this adapter can't even evaluate (bad column, too few
   points, ...) makes the whole compound claim UNDETERMINED with that
   specific reason — never silently dropped from the AND.

A claim missing any required context key, a missing file, a non-numeric
column, a `stat` that needs a second column it wasn't given, too few
data points for the requested stat, or a bad `stat` name all produce NO
evidence plus a specific, named reason via describe_gap() — never a
crash, never a silent zero.
"""

from __future__ import annotations

import csv
import math
import statistics
from pathlib import Path

from anticassiopeia.core.domain import DomainAdapter
from anticassiopeia.core.verdict import Claim, Evidence

_SINGLE_COLUMN_STATS = {
    "mean": statistics.mean,
    "min": min,
    "max": max,
    "stdev": statistics.stdev,
    "median": statistics.median,
    "p25": lambda values: statistics.quantiles(values, n=4)[0],
    "p75": lambda values: statistics.quantiles(values, n=4)[2],
}
#: Minimum sample size each stat needs before stdlib `statistics` itself won't
#: raise StatisticsError — mean/min/max/median tolerate a single value;
#: stdev needs variance (2 points); quantiles(n=4) needs 2 points. These are
#: stdlib's actual hard minimums, not an extra made-up stricter number — a
#: quartile split on exactly 2 points is a real (if uninformative) result,
#: not something worth inventing a higher bar to refuse.
_MIN_SAMPLES = {"mean": 1, "min": 1, "max": 1, "median": 1, "stdev": 2, "p25": 2, "p75": 2}
_TWO_COLUMN_STATS = {"correlation": statistics.correlation}
_MIN_SAMPLES_TWO_COLUMN = {"correlation": 2}
_ALL_STATS = set(_SINGLE_COLUMN_STATS) | set(_TWO_COLUMN_STATS)


def _resolve_paths(spec: str | list[str]) -> list[Path]:
    if isinstance(spec, str):
        return [Path(spec)]
    return [Path(p) for p in spec]


def _read_column(paths: list[Path], column: str) -> tuple[list[float] | None, int, int]:
    """Aggregates one column's numeric values across one or more CSV files, in
    order. Returns (values, total_row_count, non_numeric_rows_skipped).
    values is None if the column header is missing from ANY of the files —
    a dataset genuinely split across shards is assumed to share one schema;
    a column present in some shards but not others is a specific mismatch,
    not something to paper over by using whichever files happen to have it."""
    values: list[float] = []
    row_count = 0
    bad_rows = 0
    for path in paths:
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or column not in reader.fieldnames:
                return None, 0, 0
            for row in reader:
                row_count += 1
                try:
                    value = float(row.get(column, ""))
                except (TypeError, ValueError):
                    bad_rows += 1
                    continue
                # float() parses the literal strings "nan"/"inf"/"-inf" into
                # real IEEE non-finite values without raising -- confirmed for
                # real on UCI's own auto_mpg.csv, which spells 6 missing
                # "horsepower" readings as the literal string "NaN" (not "?",
                # not empty). A non-finite value is not a usable numeric
                # reading; treated the same as any other unparseable cell
                # (FOUND BUG, see stress_test/BUGS_FOUND.md: this used to
                # silently corrupt mean/median/percentile/correlation into
                # nan, or crash stdev outright with an uncaught StatisticsError).
                if not math.isfinite(value):
                    bad_rows += 1
                    continue
                values.append(value)
    return values, row_count, bad_rows


def _read_column_pair(
    paths: list[Path], column_a: str, column_b: str
) -> tuple[list[float] | None, list[float] | None, int, int]:
    """Same multi-file aggregation as _read_column, but for two columns read
    from the SAME row — correlation is only meaningful on paired
    observations, so a row contributes only when BOTH columns parse as
    numbers on THAT row; row i's column A is never paired with row j's
    column B. Returns (xs, ys, total_row_count, rows_skipped)."""
    xs: list[float] = []
    ys: list[float] = []
    row_count = 0
    bad_rows = 0
    for path in paths:
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or column_a not in reader.fieldnames or column_b not in reader.fieldnames:
                return None, None, 0, 0
            for row in reader:
                row_count += 1
                try:
                    x = float(row.get(column_a, ""))
                    y = float(row.get(column_b, ""))
                except (TypeError, ValueError):
                    bad_rows += 1
                    continue
                # Same non-finite guard as _read_column() above, for the same
                # real reason (see BUGS_FOUND.md) -- a NaN/Infinity in EITHER
                # column drops the whole paired row, since correlation needs
                # both values from one real observation, not one real and one
                # silently-substituted-by-nothing.
                if not (math.isfinite(x) and math.isfinite(y)):
                    bad_rows += 1
                    continue
                xs.append(x)
                ys.append(y)
    return xs, ys, row_count, bad_rows


class MLDataAdapter(DomainAdapter):
    domain_name = "ml_data"
    implemented = True

    async def gather_evidence(self, claim: Claim) -> list[Evidence]:
        self._last_compound_gap: str | None = None
        ctx = claim.context
        if "checks" in ctx:
            return self._gather_compound(ctx)
        if self._check_single(ctx) is not None:
            return []
        return [self._evaluate_single(ctx)[0]]

    def _gather_compound(self, ctx: dict) -> list[Evidence]:
        raw_checks = ctx.get("checks")
        if not isinstance(raw_checks, list) or len(raw_checks) < 2:
            self._last_compound_gap = "Compound claim must provide 'checks' as a list of 2 or more sub-checks."
            return []

        shared = {k: v for k, v in ctx.items() if k != "checks"}
        results: list[tuple[dict, Evidence, bool]] = []
        for i, raw_check in enumerate(raw_checks):
            if not isinstance(raw_check, dict):
                self._last_compound_gap = f"Sub-check {i} is not a context object: {raw_check!r}."
                return []
            check = {**shared, **raw_check}
            gap = self._check_single(check)
            if gap is not None:
                stat = raw_check.get("stat", "?")
                column = raw_check.get("column", check.get("column", "?"))
                self._last_compound_gap = f"Sub-check {i} ({stat} on {column}) could not be evaluated: {gap}"
                return []
            evidence, matched = self._evaluate_single(check)
            results.append((check, evidence, matched))

        failing = [(check, ev) for check, ev, matched in results if not matched]
        sources = "; ".join(sorted({ev.source for _, ev, _ in results}))
        locators = "; ".join(ev.locator or "" for _, ev, _ in results)

        if not failing:
            parts = ", ".join(f"{c['stat']}({c.get('column', c.get('column_b', '?'))})" for c, _, _ in results)
            snippet = f"All {len(results)} sub-checks held: {parts}. " + " | ".join(ev.snippet for _, ev, _ in results)
            return [Evidence(source=sources, snippet=snippet, stance="supports", trust=0.95, locator=locators)]

        failing_desc = "; ".join(f"{c['stat']}({c.get('column', '?')}): {ev.snippet}" for c, ev in failing)
        snippet = (
            f"Compound claim requires ALL {len(results)} sub-checks to hold; "
            f"{len(failing)} did not: {failing_desc}"
        )
        return [Evidence(source=sources, snippet=snippet, stance="contradicts", trust=0.95, locator=locators)]

    def _evaluate_single(self, ctx: dict) -> tuple[Evidence, bool]:
        """Computes one stat and builds its Evidence. Caller must have already
        confirmed `_check_single(ctx) is None`."""
        paths = _resolve_paths(ctx["dataset_path"])
        stat_name = ctx["stat"]
        expected = float(ctx["expected_value"])
        tolerance = float(ctx.get("tolerance", 1e-6))

        if stat_name in _TWO_COLUMN_STATS:
            column_desc = f"{ctx['column']},{ctx['column_b']}"
            xs, ys, row_count, bad_rows = _read_column_pair(paths, ctx["column"], ctx["column_b"])
            computed = _TWO_COLUMN_STATS[stat_name](xs, ys)
        else:
            column_desc = ctx["column"]
            values, row_count, bad_rows = _read_column(paths, ctx["column"])
            computed = _SINGLE_COLUMN_STATS[stat_name](values)

        diff = abs(computed - expected)
        matched = diff <= tolerance
        path_desc = ",".join(str(p) for p in paths)
        locator = f"{path_desc}:column={column_desc},rows={row_count}" + (
            f",skipped_non_numeric={bad_rows}" if bad_rows else ""
        )
        snippet = (
            f"Re-computed {stat_name}({column_desc}) = {computed!r} over {row_count} row(s) "
            f"(expected {expected!r}, tolerance {tolerance!r}, diff {diff!r})."
        )
        evidence = Evidence(
            source=path_desc,
            snippet=snippet,
            stance="supports" if matched else "contradicts",
            trust=0.95,  # directly re-computed from the actual file(s), not reported
            locator=locator,
        )
        return evidence, matched

    def describe_gap(self, claim: Claim, evidence: list[Evidence]) -> list[str]:
        if evidence:
            return super().describe_gap(claim, evidence)
        ctx = claim.context
        if "checks" in ctx:
            return [self._last_compound_gap or "Compound claim's sub-checks could not be evaluated."]
        gap = self._check_single(ctx)
        return [gap] if gap else ["No computed/re-run evidence found for this metric or statistical claim."]

    @staticmethod
    def _check_single(ctx: dict) -> str | None:
        """Re-derives, statelessly, why a single (sub-)check would produce no
        evidence — used by gather_evidence (to short-circuit), describe_gap
        (to explain), and _gather_compound (to validate each sub-check)."""
        required = {"dataset_path", "column", "stat", "expected_value"}
        missing_keys = required - ctx.keys()
        if missing_keys:
            return f"Claim is missing required context key(s): {sorted(missing_keys)}."

        spec = ctx["dataset_path"]
        if not isinstance(spec, (str, list)):
            return f"'dataset_path' must be a string or a list of strings, got {spec!r}."
        paths = _resolve_paths(spec)
        missing_files = [str(p) for p in paths if not p.is_file()]
        if missing_files:
            return f"Dataset file(s) not found: {missing_files} — cannot compute, cannot guess."

        stat_name = ctx["stat"]
        if stat_name not in _ALL_STATS:
            return f"Unknown stat '{stat_name}'. Supported: {sorted(_ALL_STATS)}."

        if stat_name in _TWO_COLUMN_STATS:
            if "column_b" not in ctx:
                return f"stat '{stat_name}' needs a second column — missing 'column_b' in context."
            xs, ys, _row_count, _bad = _read_column_pair(paths, ctx["column"], ctx["column_b"])
            if xs is None:
                return f"Column '{ctx['column']}' or '{ctx['column_b']}' not found in one of {[str(p) for p in paths]}."
            min_n = _MIN_SAMPLES_TWO_COLUMN[stat_name]
            if len(xs) < min_n:
                return (
                    f"Only {len(xs)} paired numeric row(s) for '{ctx['column']}'/'{ctx['column_b']}' — "
                    f"'{stat_name}' needs at least {min_n}."
                )
            return None

        values, _row_count, _bad = _read_column(paths, ctx["column"])
        if values is None:
            return f"Column '{ctx['column']}' not found in one of {[str(p) for p in paths]}."
        min_n = _MIN_SAMPLES[stat_name]
        if len(values) < min_n:
            return f"Column '{ctx['column']}' has only {len(values)} numeric value(s) — '{stat_name}' needs at least {min_n}."
        return None
