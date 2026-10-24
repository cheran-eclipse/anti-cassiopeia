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

import anticassiopeia.domains.fpga_embedded as fpga_embedded_mod
from anticassiopeia.core import Claim
from anticassiopeia.domains.fpga_embedded import FPGAEmbeddedAdapter

_SINGLE_CORNER_REPORT = "evals/fixtures/vivado_timing_report_single_corner.rpt"
_MULTI_CORNER_REPORT = "evals/fixtures/vivado_timing_report.rpt"


@pytest.fixture(autouse=True)
def _allow_tmp_path_for_fixtures(monkeypatch, tmp_path):
    """Same reasoning as test_domains_ml_data.py's identically-named fixture:
    FPGAEmbeddedAdapter() now defaults to a FIXED allowlist for the
    path-containment fix (see fpga_embedded.py's module docstring); this
    module's own fixtures write real report files under pytest's tmp_path.
    The dedicated traversal/symlink tests below escape outside tmp_path
    too, so they still exercise the real check."""
    monkeypatch.setattr(
        fpga_embedded_mod, "_DEFAULT_ALLOWED_BASE_DIRS", [*fpga_embedded_mod._DEFAULT_ALLOWED_BASE_DIRS, tmp_path]
    )


@pytest.fixture
def single_corner_report_path() -> str:
    assert Path(_SINGLE_CORNER_REPORT).is_file()
    return _SINGLE_CORNER_REPORT


@pytest.fixture
def multi_corner_report_path() -> str:
    assert Path(_MULTI_CORNER_REPORT).is_file()
    return _MULTI_CORNER_REPORT


# --- single-corner report (no "Corner:" label at all -> one corner, "DEFAULT") ---


@pytest.mark.parametrize(
    "expected_value,expected_gap_substring",
    [
        (float("nan"), "'expected_value' must be a finite number"),
        (float("inf"), "'expected_value' must be a finite number"),
        ("not-a-number", "'expected_value' is not a number"),
    ],
)
async def test_nan_and_infinity_expected_value_is_an_honest_gap_not_a_confident_wrong_verdict(
    single_corner_report_path, expected_value, expected_gap_substring
):
    """Same bug class, same fix, as ml_data.py's identically-named test:
    float("nan")/float("inf") parse with no exception, and any comparison
    against them (>=, <=, or the == comparator's epsilon check) is either
    always False or nonsensical -- a confident wrong verdict from
    unusable input, not an honest refusal."""
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="x", domain="fpga_embedded",
        context={"report_path": single_corner_report_path, "metric": "wns_ns", "comparator": ">=", "expected_value": expected_value},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert expected_gap_substring in gap[0]


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


async def test_unsupported_register_metric_name_against_a_vivado_report_is_an_honest_gap_not_a_guess(single_corner_report_path):
    """Register-map claims ARE now supported (see the dedicated SVD tests
    below) — but only against a real CMSIS-SVD file, and only under the
    exact metric names this adapter recognizes (_REGISTER_METRICS). This
    metric name ("register_address") isn't one of them, so it's treated
    as an ordinary Vivado Design Timing Summary field name and correctly
    not found — a named gap, never a fabricated address, same property
    as before this session's SVD support was added."""
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


async def test_real_register_metric_name_against_a_vivado_report_is_also_an_honest_gap(single_corner_report_path):
    """The inverse of the test above: a REAL register-map metric name, but
    pointed at a Vivado timing report instead of an SVD file — must be
    refused as a format mismatch, not silently parsed as if it were an SVD."""
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="x",
        domain="fpga_embedded",
        context={
            "report_path": single_corner_report_path,
            "metric": "register_offset",
            "peripheral": "RNG",
            "register": "DATA",
            "comparator": "==",
            "expected_value": "0xB0",
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "doesn't look like a cmsis-svd" in gap[0].lower()


async def test_path_traversal_outside_allowed_directories_is_rejected():
    """Same vulnerability and fix as test_domains_ml_data.py's identically-
    named test: report_path previously went straight into Path(...) with
    no containment check. This string starts under the real
    evals/fixtures/ allowlist entry but ../ segments walk it out to a real
    file outside every allowed directory."""
    adapter = FPGAEmbeddedAdapter()
    traversal_path = "evals/fixtures/" + "../" * 12 + "etc/passwd"
    claim = Claim(
        text="x", domain="fpga_embedded",
        context={"report_path": traversal_path, "metric": "wns_ns", "comparator": ">=", "expected_value": 0},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "not within an allowed directory" in gap[0].lower()


async def test_symlink_escaping_the_allowed_directory_is_rejected(tmp_path):
    """Same symlink-escape vector as test_domains_ml_data.py's identically-
    named test: a symlink living inside an allowed directory (tmp_path,
    widened by this module's own autouse fixture) whose real target
    resolves outside every allowed directory."""
    target_outside_everything = Path("/etc/passwd")
    assert target_outside_everything.is_file()
    symlink_path = tmp_path / "escape.rpt"
    symlink_path.symlink_to(target_outside_everything)

    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="x", domain="fpga_embedded",
        context={"report_path": str(symlink_path), "metric": "wns_ns", "comparator": ">=", "expected_value": 0},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "not within an allowed directory" in gap[0].lower()


async def test_null_byte_in_path_is_a_clean_rejection_not_a_crash():
    """Same fix as test_domains_ml_data.py's identically-named test: a path
    with an embedded null byte made Path.resolve() raise ValueError, which
    wasn't caught -- a 500 instead of a clean, named gap."""
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="x", domain="fpga_embedded",
        context={"report_path": "evals/fixtures/x\x00/../../../../etc/passwd", "metric": "wns_ns", "comparator": ">=", "expected_value": 0},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "not within an allowed directory" in gap[0].lower()


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


# --- register-map claims (CMSIS-SVD) — see fpga_embedded.py's module docstring's
# "REGISTER-MAP CLAIMS" section for the real file this is tested against and
# why SVD, not a Vivado-specific format, was picked. ---

_SVD_REGISTER_MAP = "evals/fixtures/esp32c2_register_map_excerpt.svd"


@pytest.fixture
def svd_register_map_path() -> str:
    assert Path(_SVD_REGISTER_MAP).is_file()
    return _SVD_REGISTER_MAP


async def test_register_offset_claim_that_matches_is_confirmed(svd_register_map_path):
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="RNG's DATA register is at offset 0xB0",
        domain="fpga_embedded",
        context={
            "report_path": svd_register_map_path,
            "metric": "register_offset",
            "peripheral": "RNG",
            "register": "DATA",
            "comparator": "==",
            "expected_value": "0xB0",
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "supports"  # real addressOffset is 0xB0 (176)
    assert ev[0].locator.endswith(":58")  # the exact <addressOffset> line


async def test_register_offset_claim_that_disagrees_contradicts(svd_register_map_path):
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="RNG's DATA register is at offset 0x100",
        domain="fpga_embedded",
        context={
            "report_path": svd_register_map_path,
            "metric": "register_offset",
            "peripheral": "RNG",
            "register": "DATA",
            "comparator": "==",
            "expected_value": "0x100",
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert ev[0].stance == "contradicts"  # real offset is 0xB0, not 0x100


async def test_peripheral_base_address_claim(svd_register_map_path):
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="BB peripheral is based at 0x6001D000",
        domain="fpga_embedded",
        context={
            "report_path": svd_register_map_path,
            "metric": "peripheral_base_address",
            "peripheral": "BB",
            "comparator": "==",
            "expected_value": "0x6001D000",
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert ev[0].stance == "supports"


async def test_field_bit_offset_and_width_claims(svd_register_map_path):
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="FFT_FORCE_PU field starts at bit 3 and is 1 bit wide",
        domain="fpga_embedded",
        context={
            "report_path": svd_register_map_path,
            "metric": "field_bit_offset",
            "peripheral": "BB",
            "register": "BBPD_CTRL",
            "field": "FFT_FORCE_PU",
            "comparator": "==",
            "expected_value": 3,
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert ev[0].stance == "supports"  # real bitOffset is 3

    claim2 = Claim(
        text="FFT_FORCE_PU field is 1 bit wide",
        domain="fpga_embedded",
        context={
            "report_path": svd_register_map_path,
            "metric": "field_bit_width",
            "peripheral": "BB",
            "register": "BBPD_CTRL",
            "field": "FFT_FORCE_PU",
            "comparator": "==",
            "expected_value": 1,
        },
    )
    ev2 = await adapter.gather_evidence(claim2)
    assert ev2[0].stance == "supports"


async def test_register_size_bits_claim(svd_register_map_path):
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="DATA register is 32 bits wide",
        domain="fpga_embedded",
        context={
            "report_path": svd_register_map_path,
            "metric": "register_size_bits",
            "peripheral": "RNG",
            "register": "DATA",
            "comparator": "==",
            "expected_value": 32,
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert ev[0].stance == "supports"


async def test_unknown_peripheral_is_a_named_gap_listing_real_peripherals(svd_register_map_path):
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="x",
        domain="fpga_embedded",
        context={
            "report_path": svd_register_map_path,
            "metric": "peripheral_base_address",
            "peripheral": "NOPE",
            "comparator": "==",
            "expected_value": 0,
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "bb" in gap[0].lower() and "rng" in gap[0].lower()


async def test_unknown_register_is_a_named_gap_listing_real_registers(svd_register_map_path):
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="x",
        domain="fpga_embedded",
        context={
            "report_path": svd_register_map_path,
            "metric": "register_offset",
            "peripheral": "RNG",
            "register": "GHOST_REG",
            "comparator": "==",
            "expected_value": 0,
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "data" in gap[0].lower()  # names the one register that WAS parsed


async def test_unknown_field_is_a_named_gap_listing_real_fields(svd_register_map_path):
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="x",
        domain="fpga_embedded",
        context={
            "report_path": svd_register_map_path,
            "metric": "field_bit_width",
            "peripheral": "BB",
            "register": "BBPD_CTRL",
            "field": "GHOST_FIELD",
            "comparator": "==",
            "expected_value": 0,
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "fft_force_pu" in gap[0].lower()


async def test_register_missing_without_peripheral_base_address_metric_is_a_named_gap(svd_register_map_path):
    """'register' is required for every register-map metric except
    peripheral_base_address — must be a named gap, not a KeyError."""
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="x",
        domain="fpga_embedded",
        context={
            "report_path": svd_register_map_path,
            "metric": "register_offset",
            "peripheral": "RNG",
            "comparator": "==",
            "expected_value": 0,
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "'register'" in gap[0]


async def test_field_missing_for_a_field_metric_is_a_named_gap(svd_register_map_path):
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="x",
        domain="fpga_embedded",
        context={
            "report_path": svd_register_map_path,
            "metric": "field_bit_offset",
            "peripheral": "BB",
            "register": "BBPD_CTRL",
            "comparator": "==",
            "expected_value": 0,
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "'field'" in gap[0]


async def test_invalid_expected_value_is_a_named_gap_not_a_crash(svd_register_map_path):
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="x",
        domain="fpga_embedded",
        context={
            "report_path": svd_register_map_path,
            "metric": "register_offset",
            "peripheral": "RNG",
            "register": "DATA",
            "comparator": "==",
            "expected_value": "not-a-number",
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "not a number" in gap[0].lower()


async def test_nan_expected_value_on_a_register_map_claim_is_also_an_honest_gap(svd_register_map_path):
    """Same bug class as the Vivado-path test above -- register-map claims
    coerce expected_value through _coerce_expected_value, a different code
    path, so this is checked separately rather than assumed covered."""
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="x",
        domain="fpga_embedded",
        context={
            "report_path": svd_register_map_path,
            "metric": "register_offset",
            "peripheral": "RNG",
            "register": "DATA",
            "comparator": "==",
            "expected_value": float("nan"),
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "must be a finite number" in gap[0]


async def test_register_map_path_traversal_outside_allowed_directories_is_rejected():
    """Same containment fix as the Vivado path (test_path_traversal_outside_allowed_directories_is_rejected
    above) — register-map claims go through the SAME is_path_within_allowed_dirs
    check, via _check_register(), not a second unguarded code path."""
    adapter = FPGAEmbeddedAdapter()
    traversal_path = "evals/fixtures/../../anticassiopeia/domains/fpga_embedded.py"
    claim = Claim(
        text="x",
        domain="fpga_embedded",
        context={
            "report_path": traversal_path,
            "metric": "register_offset",
            "peripheral": "RNG",
            "register": "DATA",
            "comparator": "==",
            "expected_value": 0,
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "not within an allowed directory" in gap[0].lower()
