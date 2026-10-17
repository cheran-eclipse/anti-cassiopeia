import csv

import pytest

from anticassiopeia.core import Claim
from anticassiopeia.domains.ml_data import MLDataAdapter


@pytest.fixture
def csv_path(tmp_path):
    path = tmp_path / "data.csv"
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["voltage", "note"])
        writer.writeheader()
        for v in [4.98, 5.02, 5.01, 4.99, 5.00]:
            writer.writerow({"voltage": v, "note": "ok"})
        writer.writerow({"voltage": "not_a_number", "note": "bad row"})
    return path


async def test_confirms_a_correct_mean_within_tolerance(csv_path):
    adapter = MLDataAdapter()
    claim = Claim(
        text="mean voltage is 5.0",
        domain="ml_data",
        context={"dataset_path": str(csv_path), "column": "voltage", "stat": "mean", "expected_value": 5.0, "tolerance": 0.01},
    )
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "supports"
    # row_count counts every CSV row (6: 5 numeric + 1 bad); the bad row is
    # correctly excluded from the computed mean but still accounted for, not
    # silently dropped from the record — hence rows=6, skipped_non_numeric=1.
    assert "rows=6" in ev[0].locator
    assert "skipped_non_numeric=1" in ev[0].locator


async def test_contradicts_a_wrong_mean(csv_path):
    adapter = MLDataAdapter()
    claim = Claim(
        text="mean voltage is 6.0",
        domain="ml_data",
        context={"dataset_path": str(csv_path), "column": "voltage", "stat": "mean", "expected_value": 6.0, "tolerance": 0.01},
    )
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "contradicts"


async def test_missing_file_produces_no_evidence_and_a_named_gap():
    adapter = MLDataAdapter()
    claim = Claim(
        text="x",
        domain="ml_data",
        context={"dataset_path": "/no/such/file.csv", "column": "v", "stat": "mean", "expected_value": 1.0},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "not found" in gap[0].lower()


async def test_missing_context_keys_produces_a_specific_gap():
    adapter = MLDataAdapter()
    claim = Claim(text="x", domain="ml_data", context={})
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "missing required context key" in gap[0].lower()


async def test_unknown_column_produces_a_specific_gap(csv_path):
    adapter = MLDataAdapter()
    claim = Claim(
        text="x",
        domain="ml_data",
        context={"dataset_path": str(csv_path), "column": "nonexistent_column", "stat": "mean", "expected_value": 1.0},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "not found" in gap[0].lower()


async def test_unknown_stat_produces_a_specific_gap(csv_path):
    adapter = MLDataAdapter()
    claim = Claim(
        text="x",
        domain="ml_data",
        context={"dataset_path": str(csv_path), "column": "voltage", "stat": "median", "expected_value": 1.0},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "unknown stat" in gap[0].lower()
