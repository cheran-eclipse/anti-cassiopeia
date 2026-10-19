"""
FPGA / embedded-systems domain adapter — quantum POV.

Verifies claims about synthesizable RTL / embedded hardware by parsing an
actual tool-generated report file and comparing a named metric against a
stated threshold — not by trusting a described result. See
docs/DESIGN.md §5 for why this adapter stays outside the shared
`retrieval/` package: a timing table's values are looked up by exact
key/position, not searched for in prose.

STATUS: real, offline, tested — against a REAL EDA tool's report format
this time, not an invented one.

REAL FORMAT USED: Xilinx/AMD Vivado's `report_timing_summary` text output
— specifically the "Design Timing Summary" table (WNS/TNS/WHS/THS/WPWS/
TPWS, in that fixed column order) and the "Clock Summary" table (Clock /
Waveform(ns) / Period(ns) / Frequency(MHz), with generated clocks
indented under their source clock).

HOW THIS WAS VERIFIED, stated plainly rather than just asserted: fetched
the actual raw contents of a real, checked-in Vivado timing summary report
from an open-source FPGA project (Elphel's x393 camera platform) —
https://git.elphel.com/Elphel/x393/raw/35d5291568c1a458ef066b07fe93f05689e7ad14/x393_boson-rev0.timing_summary_impl
(HTTP 200, confirmed real file, not a doc screenshot or a paraphrase). The
banner style (`| Design Timing Summary` / `| ---------------------`
inside dashed-line borders), the exact column headers, and a real data
row with real numbers (WNS 0.100, 154323 endpoints, etc.) all came from
that fetch, copied verbatim for the fixed-field order below. This
project's own `evals/fixtures/vivado_timing_report.rpt` test fixture
reuses that real structure with small synthetic numbers, same convention
`robotics.py`'s corpus excerpts already use for sourced-but-partial real
material. (A second, genuinely multi-corner real `.sta.rpt` sample was
found via search — a GitLab-hosted Quartus report with separate Slow/Fast
Fmax Summary sections — but the host required login and the content could
not actually be fetched; not used, and not invented as a substitute.)

MULTI-CORNER, stated honestly: Vivado's `report_timing_summary` reports
ONE scenario per run; it has no corner label of its own inside the table.
Real projects get multi-corner coverage by running the command once per
operating-condition scenario and keeping the outputs separate (or
concatenating them under their own naming). The `Corner: <NAME>` label
line this parser recognizes is THIS ADAPTER'S OWN convention for
representing that in one file — each individual Design Timing Summary /
Clock Summary block under a label is the real, verified Vivado format;
the act of labeling and concatenating several of them is not copied from
one single official multi-corner sample (see previous paragraph for why).
A report with no `Corner:` label at all is treated as one corner named
"DEFAULT" — single-corner reports need no change to their claim contract.

NOT EXTENDED to register-map claims: `report_timing_summary` doesn't
carry register/address-map data at all (that lives in a different, extra
report Vivado produces separately) — forcing it in here wouldn't fit the
real format, so it wasn't done, per this task's own instruction not to
force a mismatch.

Claim contract (via Claim.context):
    context = {
        "report_path": str,
        "metric": str,        # see _DESIGN_TIMING_SUMMARY_FIELDS below, or
                               # "frequency_mhz" / "period_ns" (needs "clock")
        "clock": str,          # required only for frequency_mhz / period_ns
        "corner": str = "DEFAULT",  # which `Corner: <NAME>` block to read
        "comparator": ">=" | "<=" | "==",
        "expected_value": float,
    }

PATH SAFETY (found during external security review, verified against the
real code): `report_path` previously went straight into `Path(...)` with
no containment check — since `Claim.context` is caller-supplied
(verbatim from a POST /verify body), this was an arbitrary local file
read, not just a "wrong report" bug. Every path is now resolved and
must land inside one of `allowed_base_dirs` (default: `evals/fixtures/`,
`stress_test/data/`) — see `anticassiopeia/domains/_path_safety.py`,
same fix and same reasoning as `ml_data.py`'s `dataset_path`.
"""

from __future__ import annotations

import re
from pathlib import Path

from anticassiopeia.core.domain import DomainAdapter
from anticassiopeia.core.verdict import Claim, Evidence
from anticassiopeia.domains._path_safety import is_path_within_allowed_dirs

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_ALLOWED_BASE_DIRS = [_REPO_ROOT / "evals" / "fixtures", _REPO_ROOT / "stress_test" / "data"]

# Fixed left-to-right column order of Vivado's real "Design Timing Summary"
# table — verified against the real fetch cited in the module docstring, not
# guessed. The table's human header has multi-word labels ("TNS Failing
# Endpoints") that don't whitespace-split 1:1 against the single-token data
# row beneath them, so this parses the data row by its known fixed POSITION
# (which Vivado's own table format fixes), not by token-matching the header.
_DESIGN_TIMING_SUMMARY_FIELDS = (
    "wns_ns",
    "tns_ns",
    "tns_failing_endpoints",
    "tns_total_endpoints",
    "whs_ns",
    "ths_ns",
    "ths_failing_endpoints",
    "ths_total_endpoints",
    "wpws_ns",
    "tpws_ns",
    "tpws_failing_endpoints",
    "tpws_total_endpoints",
)
_NUM = r"[-+]?\d+(?:\.\d+)?"  # matches both the float (ns) and integer (endpoint count) columns
_DESIGN_TIMING_DATA_ROW_RE = re.compile(r"^\s*(" + r")\s+(".join([_NUM] * 12) + r")\s*$")
_DESIGN_TIMING_SUMMARY_HEADER_RE = re.compile(r"Design Timing Summary")
_CLOCK_ROW_RE = re.compile(r"^\s*(\S+)\s+\{[^}]*\}\s+(" + _NUM + r")\s+(" + _NUM + r")\s*$")
_CORNER_LABEL_RE = re.compile(r"^\s*Corner:\s*(\S+)\s*$", re.IGNORECASE)
_DEFAULT_CORNER = "DEFAULT"

_COMPARATORS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: abs(a - b) < 1e-9,
}


class FPGAEmbeddedAdapter(DomainAdapter):
    domain_name = "fpga_embedded"
    implemented = True

    def __init__(self, allowed_base_dirs: list[Path] | None = None) -> None:
        self._allowed_base_dirs = allowed_base_dirs if allowed_base_dirs is not None else _DEFAULT_ALLOWED_BASE_DIRS

    async def gather_evidence(self, claim: Claim) -> list[Evidence]:
        ctx = claim.context
        if self._check(ctx) is not None:
            return []

        path = Path(ctx["report_path"])
        report = self._parse_report(path)
        corner = ctx.get("corner", _DEFAULT_CORNER)
        metric = ctx["metric"].lower()
        comparator = ctx["comparator"]
        expected = float(ctx["expected_value"])

        measured, locator_suffix = self._lookup(report[corner], metric, ctx.get("clock"))
        passes = _COMPARATORS[comparator](measured, expected)

        corner_desc = f" [corner={corner}]" if corner != _DEFAULT_CORNER else ""
        snippet = (
            f"Report states {metric}{locator_suffix} = {measured!r}{corner_desc}; "
            f"claim requires {metric} {comparator} {expected!r}."
        )
        line_no = self._find_metric_line(path, corner, metric, ctx.get("clock"))
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
    def _lookup(corner_report: dict, metric: str, clock: str | None) -> tuple[float, str]:
        if metric in ("frequency_mhz", "period_ns"):
            return corner_report["clocks"][clock][metric], f"({clock})"
        return corner_report["timing"][metric], ""

    def _check(self, ctx: dict) -> str | None:
        required = {"report_path", "metric", "comparator", "expected_value"}
        missing_keys = required - ctx.keys()
        if missing_keys:
            return f"Claim is missing required context key(s): {sorted(missing_keys)}."

        path = Path(ctx["report_path"])

        # Containment check FIRST, before even checking existence — same reasoning
        # as ml_data.py's dataset_path check: reject outside-the-allowlist paths
        # the same way whether or not they happen to exist. FOUND BUG (follow-up
        # security review): this used to list the server's real, absolute
        # allowed-directory paths in the message -- an information-disclosure
        # leak of server filesystem layout. `path` only echoes the caller's own
        # unresolved input (not a new leak); the allowed-dir listing is dropped.
        if not is_path_within_allowed_dirs(path, self._allowed_base_dirs):
            return f"Report file not found at '{path}' or not within an allowed directory — cannot parse, cannot guess."

        if not path.is_file():
            return f"Report file not found at '{path}' — cannot parse, cannot guess."

        comparator = ctx["comparator"]
        if comparator not in _COMPARATORS:
            return f"Unknown comparator '{comparator}'. Supported: {sorted(_COMPARATORS)}."

        report = FPGAEmbeddedAdapter._parse_report(path)
        if not report or all(not r["timing"] and not r["clocks"] for r in report.values()):
            return (
                f"No recognizable Vivado Design Timing Summary or Clock Summary table found in '{path}' "
                "— report format not recognized (see module docstring for the real format expected)."
            )

        corner = ctx.get("corner", _DEFAULT_CORNER)
        if corner not in report:
            return f"Corner '{corner}' not found in '{path}'. Parsed corners: {sorted(report)}."

        metric = ctx["metric"].lower()
        corner_report = report[corner]
        if metric in ("frequency_mhz", "period_ns"):
            clock = ctx.get("clock")
            if not clock:
                return (
                    f"Metric '{metric}' is per-clock — missing 'clock' in context. "
                    f"Clocks parsed for corner '{corner}': {sorted(corner_report['clocks']) or '(none)'}."
                )
            if clock not in corner_report["clocks"]:
                return (
                    f"Clock '{clock}' not found for corner '{corner}'. "
                    f"Clocks parsed: {sorted(corner_report['clocks']) or '(none)'}."
                )
            return None

        if metric not in corner_report["timing"]:
            parsed = sorted(corner_report["timing"]) if corner_report["timing"] else "(none)"
            return (
                f"Metric '{metric}' not found for corner '{corner}' in '{path}'. "
                f"Parsed Design Timing Summary fields: {parsed}."
            )
        return None

    @staticmethod
    def _parse_report(path: Path) -> dict[str, dict[str, dict]]:
        """Returns {corner_name: {"timing": {field: value}, "clocks": {clock_name:
        {"period_ns": .., "frequency_mhz": ..}}}}. A file with no `Corner: <NAME>`
        label anywhere is one corner named "DEFAULT" — see module docstring for
        why that label is this adapter's own convention, not Vivado's."""
        lines = path.read_text().splitlines()
        report: dict[str, dict[str, dict]] = {_DEFAULT_CORNER: {"timing": {}, "clocks": {}}}
        current = _DEFAULT_CORNER

        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]
            corner_m = _CORNER_LABEL_RE.match(line)
            if corner_m:
                current = corner_m.group(1)
                report.setdefault(current, {"timing": {}, "clocks": {}})
                i += 1
                continue

            if _DESIGN_TIMING_SUMMARY_HEADER_RE.search(line):
                for j in range(i + 1, min(i + 10, n)):
                    data_m = _DESIGN_TIMING_DATA_ROW_RE.match(lines[j])
                    if data_m:
                        values = [float(v) for v in data_m.groups()]
                        report[current]["timing"] = dict(zip(_DESIGN_TIMING_SUMMARY_FIELDS, values))
                        i = j
                        break

            clock_m = _CLOCK_ROW_RE.match(line)
            if clock_m:
                clock_name = clock_m.group(1)
                report[current]["clocks"][clock_name] = {
                    "period_ns": float(clock_m.group(2)),
                    "frequency_mhz": float(clock_m.group(3)),
                }
            i += 1

        return report

    @staticmethod
    def _find_metric_line(path: Path, corner: str, metric: str, clock: str | None) -> int | None:
        """Best-effort line number for the locator — finds the first line that
        plausibly carries this metric's value, for a human to re-check by hand.
        Not exact for Design Timing Summary fields (the whole data row carries
        all of them at once); exact for a specific clock's row."""
        current = _DEFAULT_CORNER
        lines = path.read_text().splitlines()
        for i, line in enumerate(lines, start=1):
            corner_m = _CORNER_LABEL_RE.match(line)
            if corner_m:
                current = corner_m.group(1)
                continue
            if current != corner:
                continue
            if clock and metric in ("frequency_mhz", "period_ns"):
                if _CLOCK_ROW_RE.match(line) and line.split()[0] == clock:
                    return i
            elif _DESIGN_TIMING_DATA_ROW_RE.match(line):
                return i
        return None
