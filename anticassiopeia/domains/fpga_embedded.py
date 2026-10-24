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

REGISTER-MAP CLAIMS, added this session: `report_timing_summary` genuinely
doesn't carry register/address-map data (unchanged fact, see paragraph
above) — so register-map claims are NOT forced through the timing parser.
Instead they're routed to a second, separate real file format: CMSIS-SVD
(System View Description), a vendor-neutral XML register-map schema used
across the embedded-systems industry (ARM's own CMSIS tooling defines the
schema; ST, Nordic, Espressif and others all publish real SVDs in it).
Deliberately picked over a Xilinx/Vivado-specific register export: this
project has no real Xilinx register-map sample to parse against (see
`evals/fixtures/esp32c2_register_map_excerpt.svd`'s header for what WAS
actually found and fetched), and SVD is the honestly-generic choice for
"register-map parsing that covers arbitrary submissions" the fpga_embedded
domain is meant to support — not scoped to one vendor's toolchain output.
`_parse_svd_register_map()` scans the real, fixed one-tag-per-line SVD
structure (verified against a real fetch, same "known real format,
position-based, not a generic XML tree walk" convention `_parse_report()`
already uses for Vivado's tables) for `<peripheral>`/`<register>`/`<field>`
blocks, and only ever reads the STATIC facts an SVD actually states —
address offsets, bit widths/offsets, base addresses — never a runtime
register's live contents, which no static file could honestly claim to
know. Metrics: `peripheral_base_address`, `register_offset`,
`register_size_bits`, `field_bit_offset`, `field_bit_width` (see
`_REGISTER_METRICS` below). Routed through entirely separate `_check`/
`gather_evidence` code paths from the Vivado timing logic above — register
claims have no "corner" concept at all, so forcing them through that
structure would be its own kind of mismatch.

Claim contract (via Claim.context):
    context = {
        "report_path": str,
        "metric": str,        # see _DESIGN_TIMING_SUMMARY_FIELDS below, or
                               # "frequency_mhz" / "period_ns" (needs "clock"),
                               # or a register-map metric (see above; needs
                               # "peripheral", and "register"/"field" as
                               # that metric requires)
        "clock": str,          # required only for frequency_mhz / period_ns
        "corner": str = "DEFAULT",  # which `Corner: <NAME>` block to read
        "peripheral": str,    # required for register-map metrics
        "register": str,       # required for register-map metrics except peripheral_base_address
        "field": str,           # required only for field_bit_offset / field_bit_width
        "comparator": ">=" | "<=" | "==",
        "expected_value": float,  # hex strings like "0xB0" are also accepted
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

# --- SVD register-map parsing (see module docstring's "REGISTER-MAP CLAIMS" section) ---

_REGISTER_METRICS = frozenset(
    {"peripheral_base_address", "register_offset", "register_size_bits", "field_bit_offset", "field_bit_width"}
)
_SVD_DEVICE_TAG_RE = re.compile(r"<device\b")
_SVD_PERIPHERALS_OPEN_RE = re.compile(r"^\s*<peripherals>\s*$")
_SVD_PERIPHERALS_CLOSE_RE = re.compile(r"^\s*</peripherals>\s*$")
_SVD_PERIPHERAL_OPEN_RE = re.compile(r"^\s*<peripheral>\s*$")
_SVD_PERIPHERAL_CLOSE_RE = re.compile(r"^\s*</peripheral>\s*$")
_SVD_REGISTER_OPEN_RE = re.compile(r"^\s*<register>\s*$")
_SVD_REGISTER_CLOSE_RE = re.compile(r"^\s*</register>\s*$")
_SVD_FIELD_OPEN_RE = re.compile(r"^\s*<field>\s*$")
_SVD_FIELD_CLOSE_RE = re.compile(r"^\s*</field>\s*$")
_SVD_GROUPING_TAGS_RE = re.compile(r"^\s*</?(?:registers|fields)>\s*$")
_SVD_NAME_RE = re.compile(r"^\s*<name>([^<]+)</name>\s*$")
_SVD_BASE_ADDRESS_RE = re.compile(r"^\s*<baseAddress>([^<]+)</baseAddress>\s*$")
_SVD_ADDRESS_OFFSET_RE = re.compile(r"^\s*<addressOffset>([^<]+)</addressOffset>\s*$")
_SVD_SIZE_RE = re.compile(r"^\s*<size>([^<]+)</size>\s*$")
_SVD_BIT_OFFSET_RE = re.compile(r"^\s*<bitOffset>([^<]+)</bitOffset>\s*$")
_SVD_BIT_WIDTH_RE = re.compile(r"^\s*<bitWidth>([^<]+)</bitWidth>\s*$")


def _coerce_expected_value(raw: float | int | str) -> float:
    """Register-map expected_value may arrive as a hex string ("0xB0", matching
    how addresses/offsets are conventionally written) or a plain number — this
    accepts either, same spirit as `_parse_svd_int` for the file's own values."""
    return float(_parse_svd_int(raw) if isinstance(raw, str) else raw)


def _parse_svd_int(text: str) -> int:
    """SVD states integers as either plain decimal or 0x-prefixed hex
    (confirmed against the real fetched files — see module docstring) —
    `int(text, 0)` handles both without guessing which."""
    return int(text.strip(), 0)


def _is_svd_file(path: Path) -> bool:
    """Cheap format sniff: a real SVD file's root element is `<device...>`
    (confirmed against two independently-sourced real files — ARM's own
    CMSIS_5 example and Espressif's published SVDs). Checked against the
    first 4000 characters, not just the first few lines — real SVDs
    (including both sources just cited) commonly carry a multi-line
    license/comment header before `<device>` actually appears."""
    try:
        head = path.read_text()[:4000]
    except OSError:
        return False
    return bool(_SVD_DEVICE_TAG_RE.search(head))


def _parse_svd_register_map(path: Path) -> dict[str, dict]:
    """Parses a real CMSIS-SVD register-map XML file by scanning its real,
    fixed one-tag-per-line structure (see module docstring) — same
    "known real format, position/tag based, not a generic XML tree walk"
    convention `_parse_report()` already uses for Vivado's text tables.
    Returns {peripheral_name: {"base_address": int | None, "_lines": {...},
    "registers": {register_name: {"address_offset": int | None,
    "size_bits": int | None, "_lines": {...}, "fields": {field_name:
    {"bit_offset": int | None, "bit_width": int | None, "_lines": {...}}}}}}}.
    `_lines` maps each populated key to the exact source line number it
    came from — the same "a human can re-check this by hand" property
    every other adapter's locator already has."""
    lines = path.read_text().splitlines()
    peripherals: dict[str, dict] = {}

    in_peripherals = False
    stack: list[str] = []  # "peripheral" | "register" | "field", tracks nesting
    cur_peripheral_name: str | None = None
    cur_register_name: str | None = None
    cur_field_name: str | None = None

    for i, line in enumerate(lines, start=1):
        if _SVD_PERIPHERALS_OPEN_RE.match(line):
            in_peripherals = True
            continue
        if _SVD_PERIPHERALS_CLOSE_RE.match(line):
            in_peripherals = False
            continue
        if not in_peripherals:
            continue  # e.g. <cpu><name>...</name></cpu> is NOT a peripheral name

        if _SVD_PERIPHERAL_OPEN_RE.match(line):
            stack.append("peripheral")
            cur_peripheral_name = None
            continue
        if _SVD_PERIPHERAL_CLOSE_RE.match(line):
            stack.pop()
            cur_peripheral_name = cur_register_name = cur_field_name = None
            continue
        if _SVD_REGISTER_OPEN_RE.match(line):
            stack.append("register")
            cur_register_name = None
            continue
        if _SVD_REGISTER_CLOSE_RE.match(line):
            stack.pop()
            cur_register_name = cur_field_name = None
            continue
        if _SVD_FIELD_OPEN_RE.match(line):
            stack.append("field")
            cur_field_name = None
            continue
        if _SVD_FIELD_CLOSE_RE.match(line):
            stack.pop()
            cur_field_name = None
            continue
        if _SVD_GROUPING_TAGS_RE.match(line):
            continue  # <registers>/<fields> group tags, not pushed onto the stack

        top = stack[-1] if stack else None

        name_m = _SVD_NAME_RE.match(line)
        if name_m:
            name = name_m.group(1).strip()
            if top == "peripheral" and cur_peripheral_name is None:
                cur_peripheral_name = name
                peripherals.setdefault(name, {"base_address": None, "_lines": {}, "registers": {}})
            elif top == "register" and cur_peripheral_name and cur_register_name is None:
                cur_register_name = name
                peripherals[cur_peripheral_name]["registers"].setdefault(
                    name, {"address_offset": None, "size_bits": None, "_lines": {}, "fields": {}}
                )
            elif top == "field" and cur_peripheral_name and cur_register_name and cur_field_name is None:
                cur_field_name = name
                reg = peripherals[cur_peripheral_name]["registers"][cur_register_name]
                reg["fields"].setdefault(name, {"bit_offset": None, "bit_width": None, "_lines": {}})
            continue

        if top == "peripheral" and cur_peripheral_name:
            m = _SVD_BASE_ADDRESS_RE.match(line)
            if m:
                periph = peripherals[cur_peripheral_name]
                periph["base_address"] = _parse_svd_int(m.group(1))
                periph["_lines"]["base_address"] = i
                continue

        if top == "register" and cur_peripheral_name and cur_register_name:
            reg = peripherals[cur_peripheral_name]["registers"][cur_register_name]
            m = _SVD_ADDRESS_OFFSET_RE.match(line)
            if m:
                reg["address_offset"] = _parse_svd_int(m.group(1))
                reg["_lines"]["address_offset"] = i
                continue
            m = _SVD_SIZE_RE.match(line)
            if m:
                reg["size_bits"] = _parse_svd_int(m.group(1))
                reg["_lines"]["size_bits"] = i
                continue

        if top == "field" and cur_peripheral_name and cur_register_name and cur_field_name:
            field = peripherals[cur_peripheral_name]["registers"][cur_register_name]["fields"][cur_field_name]
            m = _SVD_BIT_OFFSET_RE.match(line)
            if m:
                field["bit_offset"] = _parse_svd_int(m.group(1))
                field["_lines"]["bit_offset"] = i
                continue
            m = _SVD_BIT_WIDTH_RE.match(line)
            if m:
                field["bit_width"] = _parse_svd_int(m.group(1))
                field["_lines"]["bit_width"] = i
                continue

    return peripherals


class FPGAEmbeddedAdapter(DomainAdapter):
    domain_name = "fpga_embedded"
    implemented = True

    def __init__(self, allowed_base_dirs: list[Path] | None = None) -> None:
        self._allowed_base_dirs = allowed_base_dirs if allowed_base_dirs is not None else _DEFAULT_ALLOWED_BASE_DIRS

    async def gather_evidence(self, claim: Claim) -> list[Evidence]:
        ctx = claim.context
        if ctx.get("metric", "").lower() in _REGISTER_METRICS:
            return self._gather_register_evidence(ctx)

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
        ctx = claim.context
        gap = self._check_register(ctx) if ctx.get("metric", "").lower() in _REGISTER_METRICS else self._check(ctx)
        return [gap] if gap else [
            "No synthesis/timing/simulation/register-map evidence found for this RTL or embedded hardware claim."
        ]

    # --- register-map claims (see module docstring's "REGISTER-MAP CLAIMS" section) ---

    def _gather_register_evidence(self, ctx: dict) -> list[Evidence]:
        if self._check_register(ctx) is not None:
            return []

        path = Path(ctx["report_path"])
        peripherals = _parse_svd_register_map(path)
        metric = ctx["metric"].lower()
        comparator = ctx["comparator"]
        expected = _coerce_expected_value(ctx["expected_value"])
        peripheral_name = ctx["peripheral"]
        register_name = ctx.get("register")
        field_name = ctx.get("field")

        measured, suffix, line_no = self._lookup_register(peripherals, metric, peripheral_name, register_name, field_name)
        passes = _COMPARATORS[comparator](measured, expected)

        snippet = (
            f"SVD register map states {metric}{suffix} = {measured!r} (0x{int(measured):X}); "
            f"claim requires {metric} {comparator} {expected!r}."
        )
        locator = f"{path}:{line_no}" if line_no else str(path)

        return [
            Evidence(
                source=str(path),
                snippet=snippet,
                stance="supports" if passes else "contradicts",
                trust=0.9,  # directly parsed from the real SVD file, not reported secondhand
                locator=locator,
            )
        ]

    @staticmethod
    def _lookup_register(
        peripherals: dict, metric: str, peripheral_name: str, register_name: str | None, field_name: str | None
    ) -> tuple[float, str, int | None]:
        periph = peripherals[peripheral_name]
        if metric == "peripheral_base_address":
            return float(periph["base_address"]), f"({peripheral_name})", periph["_lines"].get("base_address")

        register = periph["registers"][register_name]
        if metric == "register_offset":
            return (
                float(register["address_offset"]),
                f"({peripheral_name}.{register_name})",
                register["_lines"].get("address_offset"),
            )
        if metric == "register_size_bits":
            return (
                float(register["size_bits"]),
                f"({peripheral_name}.{register_name})",
                register["_lines"].get("size_bits"),
            )

        field = register["fields"][field_name]
        key = "bit_offset" if metric == "field_bit_offset" else "bit_width"
        return (
            float(field[key]),
            f"({peripheral_name}.{register_name}.{field_name})",
            field["_lines"].get(key),
        )

    def _check_register(self, ctx: dict) -> str | None:
        required = {"report_path", "metric", "peripheral", "comparator", "expected_value"}
        metric = ctx.get("metric", "").lower()
        if metric != "peripheral_base_address":
            required.add("register")
        if metric in ("field_bit_offset", "field_bit_width"):
            required.add("field")
        missing_keys = required - ctx.keys()
        if missing_keys:
            return f"Claim is missing required context key(s): {sorted(missing_keys)}."

        path = Path(ctx["report_path"])
        if not is_path_within_allowed_dirs(path, self._allowed_base_dirs):
            return f"Report file not found at '{path}' or not within an allowed directory — cannot parse, cannot guess."
        if not path.is_file():
            return f"Report file not found at '{path}' — cannot parse, cannot guess."
        if not _is_svd_file(path):
            return (
                f"'{path}' doesn't look like a CMSIS-SVD register-map file (expected a `<device>` root "
                "element — see module docstring) — register-map metrics need a real SVD file, not a "
                "Vivado timing report."
            )

        comparator = ctx["comparator"]
        if comparator not in _COMPARATORS:
            return f"Unknown comparator '{comparator}'. Supported: {sorted(_COMPARATORS)}."

        try:
            _coerce_expected_value(ctx["expected_value"])
        except (TypeError, ValueError):
            return f"context['expected_value'] is not a number or valid hex string: {ctx['expected_value']!r}."

        peripherals = _parse_svd_register_map(path)
        if not peripherals:
            return f"No `<peripheral>` entries found in '{path}' — not a recognizable SVD register map."

        peripheral_name = ctx["peripheral"]
        if peripheral_name not in peripherals:
            return f"Peripheral '{peripheral_name}' not found in '{path}'. Parsed peripherals: {sorted(peripherals)}."
        periph = peripherals[peripheral_name]

        if metric == "peripheral_base_address":
            if periph["base_address"] is None:
                return f"Peripheral '{peripheral_name}' has no <baseAddress> parsed in '{path}'."
            return None

        register_name = ctx["register"]
        if register_name not in periph["registers"]:
            return (
                f"Register '{register_name}' not found under peripheral '{peripheral_name}' in '{path}'. "
                f"Parsed registers: {sorted(periph['registers']) or '(none)'}."
            )
        register = periph["registers"][register_name]

        if metric == "register_offset" and register["address_offset"] is None:
            return f"Register '{peripheral_name}.{register_name}' has no <addressOffset> parsed in '{path}'."
        if metric == "register_size_bits" and register["size_bits"] is None:
            return f"Register '{peripheral_name}.{register_name}' has no <size> parsed in '{path}'."

        if metric in ("field_bit_offset", "field_bit_width"):
            field_name = ctx["field"]
            if field_name not in register["fields"]:
                return (
                    f"Field '{field_name}' not found under register '{peripheral_name}.{register_name}' in "
                    f"'{path}'. Parsed fields: {sorted(register['fields']) or '(none)'}."
                )
            field = register["fields"][field_name]
            key = "bit_offset" if metric == "field_bit_offset" else "bit_width"
            if field[key] is None:
                return f"Field '{peripheral_name}.{register_name}.{field_name}' has no <{key}> parsed in '{path}'."

        return None

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
