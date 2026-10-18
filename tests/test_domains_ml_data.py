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
        # "variance" is deliberately NOT in _ALL_STATS — median/p25/p75/correlation
        # all became real, supported stats this pass (see test_median_* etc. below),
        # so this test needs a genuinely unsupported name, not "median" anymore.
        context={"dataset_path": str(csv_path), "column": "voltage", "stat": "variance", "expected_value": 1.0},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "unknown stat" in gap[0].lower()


@pytest.fixture
def two_column_csv_path(tmp_path):
    path = tmp_path / "data2.csv"
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["voltage", "current"])
        writer.writeheader()
        for v, c in zip([4.98, 5.02, 5.01, 4.99, 5.00], [1.01, 0.99, 1.00, 1.02, 0.98]):
            writer.writerow({"voltage": v, "current": c})
    return path


# --- growth: median, p25/p75, correlation (all real stdlib statistics, no new dependency) ---


async def test_median_is_computed_correctly(csv_path):
    adapter = MLDataAdapter()
    claim = Claim(
        text="median voltage is 5.0",
        domain="ml_data",
        context={
            "dataset_path": str(csv_path), "column": "voltage", "stat": "median", "expected_value": 5.0, "tolerance": 1e-9
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "supports"


async def test_p25_and_p75_are_computed_correctly(csv_path):
    # Verified independently with statistics.quantiles([4.98,5.02,5.01,4.99,5.00], n=4)
    # before writing this: [4.985, 5.0, 5.015].
    adapter = MLDataAdapter()
    for stat, expected in [("p25", 4.985), ("p75", 5.015)]:
        claim = Claim(
            text=f"{stat} voltage",
            domain="ml_data",
            context={
                "dataset_path": str(csv_path), "column": "voltage", "stat": stat, "expected_value": expected, "tolerance": 1e-9
            },
        )
        ev = await adapter.gather_evidence(claim)
        assert len(ev) == 1, stat
        assert ev[0].stance == "supports", stat


async def test_correlation_between_two_columns_is_computed_correctly(two_column_csv_path):
    # Verified independently with statistics.correlation(voltage, current) before
    # writing this: -0.6000000000000001.
    adapter = MLDataAdapter()
    claim = Claim(
        text="voltage and current correlation is -0.6",
        domain="ml_data",
        context={
            "dataset_path": str(two_column_csv_path),
            "column": "voltage",
            "column_b": "current",
            "stat": "correlation",
            "expected_value": -0.6,
            "tolerance": 1e-9,
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "supports"


async def test_correlation_missing_column_b_is_a_named_gap(two_column_csv_path):
    adapter = MLDataAdapter()
    claim = Claim(
        text="x",
        domain="ml_data",
        context={
            "dataset_path": str(two_column_csv_path), "column": "voltage", "stat": "correlation", "expected_value": -0.6
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "column_b" in gap[0]


async def test_stdev_on_too_few_points_is_a_named_gap_not_a_crash(tmp_path):
    """FOUND BUG: stdev (and now quantiles/correlation too) raise
    statistics.StatisticsError on too few data points; the pre-existing
    _check() only ever validated 'not empty', not 'enough points for THIS
    stat' — a single-numeric-value column with stat=stdev used to crash
    gather_evidence() with an uncaught exception instead of a named gap."""
    path = tmp_path / "one_row.csv"
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["voltage"])
        writer.writeheader()
        writer.writerow({"voltage": 5.0})
    adapter = MLDataAdapter()
    claim = Claim(
        text="x",
        domain="ml_data",
        context={"dataset_path": str(path), "column": "voltage", "stat": "stdev", "expected_value": 0.0},
    )
    ev = await adapter.gather_evidence(claim)  # must not raise
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "at least 2" in gap[0]


# --- growth: multi-file datasets ---


async def test_multi_file_dataset_aggregates_rows_across_files():
    # Verified independently: combined mean of both fixture files' voltage
    # columns (10 rows total) is exactly 5.0.
    adapter = MLDataAdapter()
    claim = Claim(
        text="combined mean voltage across both batches is 5.0",
        domain="ml_data",
        context={
            "dataset_path": ["evals/fixtures/sample_measurements.csv", "evals/fixtures/sample_measurements_2.csv"],
            "column": "voltage",
            "stat": "mean",
            "expected_value": 5.0,
            "tolerance": 1e-9,
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "supports"
    assert "rows=10" in ev[0].locator


async def test_multi_file_dataset_missing_column_in_one_file_is_a_named_gap(tmp_path, csv_path):
    other = tmp_path / "other.csv"
    with other.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["current"])  # no 'voltage' column in this shard
        writer.writeheader()
        writer.writerow({"current": 1.0})
    adapter = MLDataAdapter()
    claim = Claim(
        text="x",
        domain="ml_data",
        context={"dataset_path": [str(csv_path), str(other)], "column": "voltage", "stat": "mean", "expected_value": 5.0},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "not found in one of" in gap[0].lower()


# --- growth: compound (AND) claims, enforced by this adapter, not engine.py's generic sum ---


async def test_compound_claim_confirmed_when_all_subchecks_hold(csv_path):
    adapter = MLDataAdapter()
    claim = Claim(
        text="mean is ~5.0 and stdev is ~0.0158",
        domain="ml_data",
        context={
            "dataset_path": str(csv_path),
            "column": "voltage",
            "checks": [
                {"stat": "mean", "expected_value": 5.0, "tolerance": 0.01},
                {"stat": "stdev", "expected_value": 0.0158, "tolerance": 0.001},
            ],
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "supports"
    assert "All 2 sub-checks held" in ev[0].snippet


async def test_compound_claim_with_one_false_subcheck_is_contradicted_not_confirmed(csv_path):
    """The honest-gap case the task explicitly asks for: one part true, one
    part genuinely false — must NOT come back CONFIRMED, and the reason
    must name which sub-check failed, not a generic 'not fully supported'."""
    adapter = MLDataAdapter()
    claim = Claim(
        text="mean is ~5.0 and stdev is ~9.0 (false)",
        domain="ml_data",
        context={
            "dataset_path": str(csv_path),
            "column": "voltage",
            "checks": [
                {"stat": "mean", "expected_value": 5.0, "tolerance": 0.01},  # true
                {"stat": "stdev", "expected_value": 9.0, "tolerance": 0.001},  # false
            ],
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "contradicts"
    assert "stdev" in ev[0].snippet  # names WHICH sub-check failed, not a generic message


async def test_compound_claim_with_uncomputable_subcheck_is_undetermined_not_confirmed(csv_path):
    adapter = MLDataAdapter()
    claim = Claim(
        text="mean is ~5.0 and some nonexistent column's mean is 1.0",
        domain="ml_data",
        context={
            "dataset_path": str(csv_path),
            "checks": [
                {"column": "voltage", "stat": "mean", "expected_value": 5.0, "tolerance": 0.01},
                {"column": "nonexistent_column", "stat": "mean", "expected_value": 1.0},
            ],
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "sub-check 1" in gap[0].lower()
    assert "not found" in gap[0].lower()


async def test_compound_claim_needs_at_least_two_checks():
    adapter = MLDataAdapter()
    claim = Claim(
        text="x",
        domain="ml_data",
        context={
            "dataset_path": "evals/fixtures/sample_measurements.csv",
            "checks": [{"column": "voltage", "stat": "mean", "expected_value": 5.0}],
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "2 or more" in gap[0]


# --- FOUND BUG (see stress_test/BUGS_FOUND.md): float() parses the literal
# strings "nan"/"inf"/"-inf" without raising, so a real-world missing-value
# marker spelled that way (confirmed on UCI's own auto_mpg.csv, which spells
# 6 missing "horsepower" readings as the literal string "NaN") used to
# silently corrupt mean/median/percentile/correlation into nan, or crash
# stdev outright with an uncaught StatisticsError. Fixed by requiring
# math.isfinite() after float() in both _read_column() and
# _read_column_pair(). Real file, real numbers -- independently verified
# against this exact data before writing this test, same as every other
# real-data test in this project. ---

_AUTO_MPG_PATH = "evals/fixtures/auto_mpg.csv"


async def test_nan_valued_rows_are_excluded_not_silently_corrupting_mean():
    adapter = MLDataAdapter()
    claim = Claim(
        text="x",
        domain="ml_data",
        context={
            "dataset_path": _AUTO_MPG_PATH, "column": "horsepower", "stat": "mean",
            "expected_value": 104.46938775510205, "tolerance": 1e-6,
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "supports"
    assert "rows=398" in ev[0].locator  # every row counted
    assert "skipped_non_numeric=6" in ev[0].locator  # the 6 "NaN" rows correctly excluded


async def test_nan_valued_rows_are_excluded_from_median_and_percentiles():
    adapter = MLDataAdapter()
    for stat, expected in [("median", 93.5), ("p25", 75.0), ("p75", 128.0)]:
        claim = Claim(
            text="x", domain="ml_data",
            context={"dataset_path": _AUTO_MPG_PATH, "column": "horsepower", "stat": stat,
                     "expected_value": expected, "tolerance": 1e-6},
        )
        ev = await adapter.gather_evidence(claim)
        assert len(ev) == 1, stat
        assert ev[0].stance == "supports", stat  # was silently WRONG (e.g. median=115.0, not 93.5) before the fix


async def test_nan_valued_rows_no_longer_crash_stdev():
    """This used to raise an uncaught statistics.StatisticsError straight out
    of gather_evidence() -- the core property this test proves is "does not
    raise", not just "gives the right number"."""
    adapter = MLDataAdapter()
    claim = Claim(
        text="x", domain="ml_data",
        context={"dataset_path": _AUTO_MPG_PATH, "column": "horsepower", "stat": "stdev",
                 "expected_value": 38.49115993282849, "tolerance": 1e-6},
    )
    ev = await adapter.gather_evidence(claim)  # must not raise
    assert len(ev) == 1
    assert ev[0].stance == "supports"


async def test_nan_valued_rows_are_excluded_from_correlation():
    adapter = MLDataAdapter()
    claim = Claim(
        text="x", domain="ml_data",
        context={
            "dataset_path": _AUTO_MPG_PATH, "column": "horsepower", "column_b": "weight",
            "stat": "correlation", "expected_value": 0.8645377375741444, "tolerance": 1e-6,
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "supports"


async def test_clean_column_with_zero_non_finite_values_is_unaffected(csv_path):
    """Regression guard: the fix must not change behavior on data that was
    already clean -- same fixture, same exact assertions as the original
    (pre-fix) mean test, still passing unchanged."""
    adapter = MLDataAdapter()
    claim = Claim(
        text="mean voltage is 5.0", domain="ml_data",
        context={"dataset_path": str(csv_path), "column": "voltage", "stat": "mean",
                 "expected_value": 5.0, "tolerance": 0.01},
    )
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "supports"
    assert "rows=6" in ev[0].locator
    assert "skipped_non_numeric=1" in ev[0].locator  # the pre-existing "not_a_number" bad row only
