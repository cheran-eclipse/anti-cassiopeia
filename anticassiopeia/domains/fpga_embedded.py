"""
FPGA / embedded-systems domain adapter — quantum POV.

Verifies claims about synthesizable RTL / embedded hardware by parsing an
actual tool-generated report file and comparing a named metric against a
stated threshold — not by trusting a described result.

STATUS: real, offline, tested — against a synthetic fixture report in
this adapter's own simple format (see below), NOT against real Vivado /
Yosys / Quartus output. Stated plainly rather than implied: this parser
has not been verified against a real EDA tool's report syntax. Treat the
report-format assumption as the thing most likely to break first when
this meets real data, and fix the regex/format against a real report
before trusting a verdict from actual synthesis output.

Report format assumed (one `key: value` per line, case-insensitive key,
value is the last whitespace-separated token with an optional unit
suffix stripped):

    max_frequency_mhz: 142.5
    slack_ns: 0.32
    luts_used: 18422

Claim contract (via Claim.context):
    context = {
        "report_path": str,
        "metric": str,              # e.g. "max_frequency_mhz", must match a report key
        "comparator": ">=" | "<=" | "==",
        "expected_value": float,
    }
"""

from __future__ import annotations

import re
from pathlib import Path

from anticassiopeia.core.domain import DomainAdapter
from anticassiopeia.core.verdict import Claim, Evidence

_LINE_RE = re.compile(r"^\s*([A-Za-z0-9_]+)\s*:\s*([-+0-9.eE]+)\s*[A-Za-z%]*\s*$")

_COMPARATORS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: abs(a - b) < 1e-9,
}


class FPGAEmbeddedAdapter(DomainAdapter):
    domain_name = "fpga_embedded"
    implemented = True

    async def gather_evidence(self, claim: Claim) -> list[Evidence]:
        ctx = claim.context
        if self._check(ctx) is not None:
            return []

        path = Path(ctx["report_path"])
        report = self._parse_report(path)
        metric = ctx["metric"].lower()
        measured = report[metric]
        comparator = ctx["comparator"]
        expected = float(ctx["expected_value"])
        passes = _COMPARATORS[comparator](measured, expected)

        snippet = f"Report states {metric} = {measured!r}; claim requires {metric} {comparator} {expected!r}."
        # line number of the matching entry, for a precise locator
        line_no = self._find_line(path, metric)
        locator = f"{path}:{line_no}" if line_no else str(path)

        return [
            Evidence(
                source=str(path),
                snippet=snippet,
                stance="supports" if passes else "contradicts",
                trust=0.9,  # directly parsed from the report file, not reported secondhand
                locator=locator,
            )
        ]

    def describe_gap(self, claim: Claim, evidence: list[Evidence]) -> list[str]:
        if evidence:
            return super().describe_gap(claim, evidence)
        gap = self._check(claim.context)
        return [gap] if gap else [
            "No synthesis/timing/simulation evidence found for this RTL or embedded hardware claim."
        ]

    @staticmethod
    def _check(ctx: dict) -> str | None:
        required = {"report_path", "metric", "comparator", "expected_value"}
        missing_keys = required - ctx.keys()
        if missing_keys:
            return f"Claim is missing required context key(s): {sorted(missing_keys)}."

        path = Path(ctx["report_path"])
        if not path.is_file():
            return f"Report file not found at '{path}' — cannot parse, cannot guess."

        comparator = ctx["comparator"]
        if comparator not in _COMPARATORS:
            return f"Unknown comparator '{comparator}'. Supported: {sorted(_COMPARATORS)}."

        report = FPGAEmbeddedAdapter._parse_report(path)
        metric = ctx["metric"].lower()
        if metric not in report:
            parsed_keys = sorted(report) if report else "(none — report format not recognized; see module docstring)"
            return f"Metric '{metric}' not found in '{path}'. Parsed keys: {parsed_keys}."
        return None

    @staticmethod
    def _parse_report(path: Path) -> dict[str, float]:
        report: dict[str, float] = {}
        for line in path.read_text().splitlines():
            m = _LINE_RE.match(line)
            if m:
                key, value = m.group(1).lower(), m.group(2)
                report[key] = float(value)
        return report

    @staticmethod
    def _find_line(path: Path, metric: str) -> int | None:
        for i, line in enumerate(path.read_text().splitlines(), start=1):
            if line.strip().lower().startswith(metric + ":"):
                return i
        return None
