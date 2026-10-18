"""
Independent ground-truth oracle for fpga_embedded claims.

Deliberately does NOT import anticassiopeia.domains.fpga_embedded — parses
the same real Vivado report_timing_summary format with different code:
a single-pass line scanner using plain string splitting instead of the
production adapter's compiled multi-group regex approach, and a different
internal data shape (flat dict per corner instead of the production
adapter's {"timing": {...}, "clocks": {...}} nesting). Two independently
written parsers over the same real report text, not one path trusted
twice.
"""

from __future__ import annotations

_FIELD_ORDER = (
    "wns_ns", "tns_ns", "tns_failing_endpoints", "tns_total_endpoints",
    "whs_ns", "ths_ns", "ths_failing_endpoints", "ths_total_endpoints",
    "wpws_ns", "tpws_ns", "tpws_failing_endpoints", "tpws_total_endpoints",
)


def _is_number(tok: str) -> bool:
    try:
        float(tok)
        return True
    except ValueError:
        return False


def parse_report(path: str) -> dict[str, dict]:
    """Returns {corner: {field_or_clock_name: value}} — timing fields and
    clock frequency/period are flattened into ONE dict per corner here
    (clock entries keyed as "<clock>.period_ns" / "<clock>.frequency_mhz"),
    a deliberately different shape than production's nested dict, so a
    comparison test has to look values up by (corner, metric) pairs either
    way rather than accidentally relying on identical structure."""
    text = open(path).read()
    lines = text.splitlines()

    corners: dict[str, dict] = {"DEFAULT": {}}
    current = "DEFAULT"

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        if stripped.lower().startswith("corner:"):
            current = stripped.split(":", 1)[1].strip()
            corners.setdefault(current, {})
            i += 1
            continue

        if "Design Timing Summary" in line:
            # scan forward for a line whose whitespace-split tokens are ALL
            # numeric and there are exactly 12 of them (the fixed real
            # column count) -- independent of the production regex.
            for j in range(i + 1, min(i + 10, n)):
                toks = lines[j].split()
                if len(toks) == 12 and all(_is_number(t) for t in toks):
                    for field, tok in zip(_FIELD_ORDER, toks):
                        corners[current][field] = float(tok)
                    i = j
                    break

        # Clock Summary rows: "<name> {a b} <period> <freq>" possibly indented.
        if "{" in line and "}" in line:
            before_brace = line[: line.index("{")].split()
            after_brace = line[line.index("}") + 1 :].split()
            if len(before_brace) == 1 and len(after_brace) == 2 and all(_is_number(t) for t in after_brace):
                clock_name = before_brace[0]
                corners[current][f"{clock_name}.period_ns"] = float(after_brace[0])
                corners[current][f"{clock_name}.frequency_mhz"] = float(after_brace[1])

        i += 1

    return corners


if __name__ == "__main__":
    report = parse_report("evals/fixtures/vivado_timing_report_single_corner.rpt")
    print(report)
    assert report["DEFAULT"]["wns_ns"] == 0.320
    assert report["DEFAULT"]["clk_main.frequency_mhz"] == 142.857
    print("smoke test OK")
