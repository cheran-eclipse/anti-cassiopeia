"""
Tests the fpga_embedded adapter against a REAL EDA tool report format —
Xilinx/AMD Vivado's `report_timing_summary` (Design Timing Summary +
Clock Summary tables) — not an invented one. The column headers and
table structure used in `evals/fixtures/vivado_timing_report*.rpt` were
copied verbatim from a real, fetched open-source project's actual Vivado
report; see `anticassiopeia/domains/fpga_embedded.py`'s module docstring
for the exact URL and how that was verified. Only the numbers are
synthetic, same convention `robotics.py`'s corpus excerpts already use.
"""

from pathlib import Path

import pytest

from anticassiopeia.core import Claim
from anticassiopeia.domains.fpga_embedded import FPGAEmbeddedAdapter

_SINGLE_CORNER_REPORT = "evals/fixtures/vivado_timing_report_single_corner.rpt"
_MULTI_CORNER_REPORT = "evals/fixtures/vivado_timing_report.rpt"


@pytest.fixture
def single_corner_report_path() -> str:
    assert Path(_SINGLE_CORNER_REPORT).is_file()
    return _SINGLE_CORNER_REPORT


@pytest.fixture
def multi_corner_report_path() -> str:
    assert Path(_MULTI_CORNER_REPORT).is_file()
    return _MULTI_CORNER_REPORT


# --- single-corner report (no "Corner:" label at all -> one corner, "DEFAULT") ---


async def test_confirms_a_design_timing_summary_field_that_clears_the_threshold(single_corner_report_path):
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="worst setup slack is at least 0.1 ns",
        domain="fpga_embedded",
        context={"report_path": single_corner_report_path, "metric": "wns_ns", "comparator": ">=", "expected_value": 0.1},
    )
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "supports"  # real wns_ns is 0.320


async def test_contradicts_a_design_timing_summary_field_that_fails_the_threshold(single_corner_report_path):
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="worst setup slack is at least 1.0 ns",
        domain="fpga_embedded",
        context={"report_path": single_corner_report_path, "metric": "wns_ns", "comparator": ">=", "expected_value": 1.0},
    )
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "contradicts"  # real wns_ns is 0.320, not >= 1.0


async def test_equality_comparator_on_an_endpoint_count(single_corner_report_path):
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="TNS total endpoints is exactly 200",
        domain="fpga_embedded",
        context={
            "report_path": single_corner_report_path,
            "metric": "tns_total_endpoints",
            "comparator": "==",
            "expected_value": 200,
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert ev[0].stance == "supports"


async def test_clock_frequency_metric_requires_and_uses_the_named_clock(single_corner_report_path):
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="clk_main runs at at least 100 MHz",
        domain="fpga_embedded",
        context={
            "report_path": single_corner_report_path,
            "metric": "frequency_mhz",
            "clock": "clk_main",
            "comparator": ">=",
            "expected_value": 100,
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert ev[0].stance == "supports"  # real frequency is 142.857 MHz


async def test_frequency_metric_without_a_clock_is_a_named_gap(single_corner_report_path):
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="x",
        domain="fpga_embedded",
        context={
            "report_path": single_corner_report_path, "metric": "frequency_mhz", "comparator": ">=", "expected_value": 100
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "missing 'clock'" in gap[0].lower()
    assert "clk_main" in gap[0]  # names what clocks WERE parsed


async def test_unrecognized_metric_lists_the_fields_that_WERE_parsed(single_corner_report_path):
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="x",
        domain="fpga_embedded",
        context={"report_path": single_corner_report_path, "metric": "ghost_metric", "comparator": ">=", "expected_value": 0},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "wns_ns" in gap[0]  # names what it DID find, not just what it didn't


async def test_register_map_style_claim_is_an_honest_gap_not_a_guess(single_corner_report_path):
    """The real report format genuinely has no register/address-map data —
    see module docstring for why this wasn't forced in. Must be a named
    gap, never a fabricated address."""
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="REG_CTRL is mapped at 0x40",
        domain="fpga_embedded",
        context={"report_path": single_corner_report_path, "metric": "register_address", "comparator": "==", "expected_value": 64},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "not found" in gap[0].lower()


async def test_missing_report_file(tmp_path):
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="x",
        domain="fpga_embedded",
        context={"report_path": str(tmp_path / "nope.rpt"), "metric": "x", "comparator": ">=", "expected_value": 0},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "not found" in gap[0].lower()


async def test_unrecognized_report_format_is_a_named_gap_not_a_crash(tmp_path):
    path = tmp_path / "garbage.rpt"
    path.write_text("this file has no Design Timing Summary or Clock Summary table in it at all\njust prose\n")
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="x",
        domain="fpga_embedded",
        context={"report_path": str(path), "metric": "wns_ns", "comparator": ">=", "expected_value": 0},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "not recognized" in gap[0].lower()


# --- multi-corner report ("Corner: <NAME>" labels around repeated real-format blocks) ---


async def test_multi_corner_report_reads_the_correct_corners_own_row(multi_corner_report_path):
    adapter = FPGAEmbeddedAdapter()
    slow = Claim(
        text="SLOW_MAX worst setup slack is at least 0.5 ns",
        domain="fpga_embedded",
        context={
            "report_path": multi_corner_report_path,
            "metric": "wns_ns",
            "corner": "SLOW_MAX",
            "comparator": ">=",
            "expected_value": 0.5,
        },
    )
    fast = Claim(
        text="FAST_MIN worst setup slack is at least 5 ns",
        domain="fpga_embedded",
        context={
            "report_path": multi_corner_report_path,
            "metric": "wns_ns",
            "corner": "FAST_MIN",
            "comparator": ">=",
            "expected_value": 5,
        },
    )
    slow_ev = await adapter.gather_evidence(slow)
    fast_ev = await adapter.gather_evidence(fast)

    assert slow_ev[0].stance == "supports"  # SLOW_MAX real wns_ns = 0.820
    assert fast_ev[0].stance == "contradicts"  # FAST_MIN real wns_ns = 1.950, not >= 5
    assert "corner=SLOW_MAX" in slow_ev[0].snippet
    assert "corner=FAST_MIN" in fast_ev[0].snippet


async def test_unknown_corner_is_a_named_gap_listing_real_corners(multi_corner_report_path):
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="x",
        domain="fpga_embedded",
        context={
            "report_path": multi_corner_report_path,
            "metric": "wns_ns",
            "corner": "TYPICAL",
            "comparator": ">=",
            "expected_value": 0,
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "slow_max" in gap[0].lower()
    assert "fast_min" in gap[0].lower()


async def test_multi_corner_clock_summary_is_identical_across_corners_in_this_fixture(multi_corner_report_path):
    """Both corners in this fixture share the same Clock Summary (only the
    Design Timing Summary slack differs across corners, which is realistic —
    clock frequencies come from the design's constraints, not the corner)."""
    adapter = FPGAEmbeddedAdapter()
    for corner in ("SLOW_MAX", "FAST_MIN"):
        claim = Claim(
            text=f"{corner}: clk_sys runs at at least 100 MHz",
            domain="fpga_embedded",
            context={
                "report_path": multi_corner_report_path,
                "metric": "frequency_mhz",
                "clock": "clk_sys",
                "corner": corner,
                "comparator": ">=",
                "expected_value": 100,
            },
        )
        ev = await adapter.gather_evidence(claim)
        assert ev[0].stance == "supports", corner
