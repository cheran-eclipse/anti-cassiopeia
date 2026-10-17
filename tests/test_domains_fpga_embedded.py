import pytest

from anticassiopeia.core import Claim
from anticassiopeia.domains.fpga_embedded import FPGAEmbeddedAdapter


@pytest.fixture
def report_path(tmp_path):
    path = tmp_path / "timing.txt"
    path.write_text("max_frequency_mhz: 142.5\nslack_ns: 0.32\nluts_used: 18422\n")
    return path


async def test_confirms_a_metric_that_clears_the_threshold(report_path):
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="meets 100 MHz",
        domain="fpga_embedded",
        context={"report_path": str(report_path), "metric": "max_frequency_mhz", "comparator": ">=", "expected_value": 100},
    )
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "supports"
    assert ev[0].locator.endswith(":1")  # max_frequency_mhz is line 1


async def test_contradicts_a_metric_that_fails_the_threshold(report_path):
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="meets 200 MHz",
        domain="fpga_embedded",
        context={"report_path": str(report_path), "metric": "max_frequency_mhz", "comparator": ">=", "expected_value": 200},
    )
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "contradicts"


async def test_equality_comparator(report_path):
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="luts used is exactly 18422",
        domain="fpga_embedded",
        context={"report_path": str(report_path), "metric": "luts_used", "comparator": "==", "expected_value": 18422},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev[0].stance == "supports"


async def test_unrecognized_metric_lists_the_metrics_that_WERE_parsed(report_path):
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="x",
        domain="fpga_embedded",
        context={"report_path": str(report_path), "metric": "ghost", "comparator": ">=", "expected_value": 0},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "max_frequency_mhz" in gap[0]  # names what it DID find, not just what it didn't


async def test_missing_report_file(tmp_path):
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="x",
        domain="fpga_embedded",
        context={"report_path": str(tmp_path / "nope.txt"), "metric": "x", "comparator": ">=", "expected_value": 0},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "not found" in gap[0].lower()


async def test_unrecognized_lines_are_silently_skipped_not_misparsed(tmp_path):
    path = tmp_path / "report.txt"
    path.write_text("# a comment line, not key: value\nmax_frequency_mhz: 100\ngarbage line with no colon\n")
    adapter = FPGAEmbeddedAdapter()
    claim = Claim(
        text="x",
        domain="fpga_embedded",
        context={"report_path": str(path), "metric": "max_frequency_mhz", "comparator": ">=", "expected_value": 100},
    )
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "supports"
