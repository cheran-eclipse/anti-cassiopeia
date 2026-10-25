import csv
from pathlib import Path

import pytest

import anticassiopeia.domains.quant as ml_data_mod
from anticassiopeia.core import Claim
from anticassiopeia.domains.quant import QuantAdapter


@pytest.fixture(autouse=True)
def _allow_tmp_path_for_fixtures(monkeypatch, tmp_path):
    """QuantAdapter() now defaults to a FIXED allowlist of real directories
    (evals/fixtures/, stress_test/data/) for the path-containment fix (see
    quant.py's module docstring) — this test module's own fixtures write
    real CSVs under pytest's tmp_path, which is legitimately outside that
    production allowlist. Widening the DEFAULT for the duration of each
    test (not passing allowed_base_dirs explicitly at 20+ call sites) keeps
    every existing `QuantAdapter()` call working; the dedicated path-
    traversal/symlink tests below do NOT rely on this widening — they
    escape outside tmp_path too, so they still exercise the real check."""
    monkeypatch.setattr(
        ml_data_mod, "_DEFAULT_ALLOWED_BASE_DIRS", [*ml_data_mod._DEFAULT_ALLOWED_BASE_DIRS, tmp_path]
    )


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


@pytest.mark.parametrize(
    "expected_value,tolerance,expected_gap_substring",
    [
        (float("nan"), 0.01, "'expected_value' must be a finite number"),
        (float("inf"), 0.01, "'expected_value' must be a finite number"),
        (float("-inf"), 0.01, "'expected_value' must be a finite number"),
        (5.0, float("nan"), "'tolerance' must be a finite number"),
        (5.0, -1.0, "'tolerance' must not be negative"),
        ("not-a-number", 0.01, "'expected_value' is not a number"),
    ],
)
async def test_nan_infinity_and_negative_tolerance_are_an_honest_gap_not_a_confident_wrong_verdict(
    csv_path, expected_value, tolerance, expected_gap_substring
):
    """FOUND BUG (external review, "the worst bug of this round"):
    float("nan") parses with no exception, so diff = abs(computed - nan)
    is nan, and `nan <= tolerance` is ALWAYS False in Python -- this used
    to silently produce a confident CONTRADICTED verdict from unusable
    input, the exact failure mode this project exists to prevent, in its
    own core adapter. Same for Infinity and a negative tolerance."""
    adapter = QuantAdapter()
    claim = Claim(
        text="x", domain="quant",
        context={
            "dataset_path": str(csv_path), "column": "voltage", "stat": "mean",
            "expected_value": expected_value, "tolerance": tolerance,
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == [], f"expected_value={expected_value!r} must never produce a confident verdict"
    gap = adapter.describe_gap(claim, ev)
    assert expected_gap_substring in gap[0]


async def test_confirms_a_correct_mean_within_tolerance(csv_path):
    adapter = QuantAdapter()
    claim = Claim(
        text="mean voltage is 5.0",
        domain="quant",
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
    adapter = QuantAdapter()
    claim = Claim(
        text="mean voltage is 6.0",
        domain="quant",
        context={"dataset_path": str(csv_path), "column": "voltage", "stat": "mean", "expected_value": 6.0, "tolerance": 0.01},
    )
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "contradicts"


async def test_missing_file_produces_no_evidence_and_a_named_gap():
    adapter = QuantAdapter()
    claim = Claim(
        text="x",
        domain="quant",
        context={"dataset_path": "/no/such/file.csv", "column": "v", "stat": "mean", "expected_value": 1.0},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "not found" in gap[0].lower()


async def test_missing_context_keys_produces_a_specific_gap():
    adapter = QuantAdapter()
    claim = Claim(text="x", domain="quant", context={})
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "missing required context key" in gap[0].lower()


async def test_unknown_column_produces_a_specific_gap(csv_path):
    adapter = QuantAdapter()
    claim = Claim(
        text="x",
        domain="quant",
        context={"dataset_path": str(csv_path), "column": "nonexistent_column", "stat": "mean", "expected_value": 1.0},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "not found" in gap[0].lower()


async def test_unknown_stat_produces_a_specific_gap(csv_path):
    adapter = QuantAdapter()
    claim = Claim(
        text="x",
        domain="quant",
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
    adapter = QuantAdapter()
    claim = Claim(
        text="median voltage is 5.0",
        domain="quant",
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
    adapter = QuantAdapter()
    for stat, expected in [("p25", 4.985), ("p75", 5.015)]:
        claim = Claim(
            text=f"{stat} voltage",
            domain="quant",
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
    adapter = QuantAdapter()
    claim = Claim(
        text="voltage and current correlation is -0.6",
        domain="quant",
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
    adapter = QuantAdapter()
    claim = Claim(
        text="x",
        domain="quant",
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
    adapter = QuantAdapter()
    claim = Claim(
        text="x",
        domain="quant",
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
    adapter = QuantAdapter()
    claim = Claim(
        text="combined mean voltage across both batches is 5.0",
        domain="quant",
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
    adapter = QuantAdapter()
    claim = Claim(
        text="x",
        domain="quant",
        context={"dataset_path": [str(csv_path), str(other)], "column": "voltage", "stat": "mean", "expected_value": 5.0},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "not found in one of" in gap[0].lower()


# --- growth: compound (AND) claims, enforced by this adapter, not engine.py's generic sum ---


async def test_compound_claim_confirmed_when_all_subchecks_hold(csv_path):
    adapter = QuantAdapter()
    claim = Claim(
        text="mean is ~5.0 and stdev is ~0.0158",
        domain="quant",
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
    adapter = QuantAdapter()
    claim = Claim(
        text="mean is ~5.0 and stdev is ~9.0 (false)",
        domain="quant",
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
    adapter = QuantAdapter()
    claim = Claim(
        text="mean is ~5.0 and some nonexistent column's mean is 1.0",
        domain="quant",
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
    adapter = QuantAdapter()
    claim = Claim(
        text="x",
        domain="quant",
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
    adapter = QuantAdapter()
    claim = Claim(
        text="x",
        domain="quant",
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
    adapter = QuantAdapter()
    for stat, expected in [("median", 93.5), ("p25", 75.0), ("p75", 128.0)]:
        claim = Claim(
            text="x", domain="quant",
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
    adapter = QuantAdapter()
    claim = Claim(
        text="x", domain="quant",
        context={"dataset_path": _AUTO_MPG_PATH, "column": "horsepower", "stat": "stdev",
                 "expected_value": 38.49115993282849, "tolerance": 1e-6},
    )
    ev = await adapter.gather_evidence(claim)  # must not raise
    assert len(ev) == 1
    assert ev[0].stance == "supports"


async def test_nan_valued_rows_are_excluded_from_correlation():
    adapter = QuantAdapter()
    claim = Claim(
        text="x", domain="quant",
        context={
            "dataset_path": _AUTO_MPG_PATH, "column": "horsepower", "column_b": "weight",
            "stat": "correlation", "expected_value": 0.8645377375741444, "tolerance": 1e-6,
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "supports"


@pytest.fixture
def air_quality_csv_path(tmp_path):
    """Filename MUST be exactly 'air_quality.csv' -- the sentinel lookup
    (_DATASET_SENTINELS) matches by filename, not content, same as the real
    UCI file this is a small stand-in for."""
    path = tmp_path / "air_quality.csv"
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["CO(GT)", "NOx(GT)"])
        writer.writeheader()
        for co, nox in [(2.6, 166), (2.0, 103), (-200, 131), (1.2, -200), (2.2, 150)]:
            writer.writerow({"CO(GT)": co, "NOx(GT)": nox})
    return path


async def test_air_quality_sentinel_excluded_from_mean(air_quality_csv_path):
    """FIXED (was 'disclosed, not fixed' -- see quant.py's module
    docstring): -200 is air_quality.csv's own documented missing-value
    marker; a real -200 CO(GT) reading used to be averaged in literally.
    CO(GT) column is [2.6, 2.0, -200, 1.2, 2.2]; only the row where CO(GT)
    itself is -200 is excluded (NOx(GT)'s own -200, on a different row, is
    irrelevant to CO(GT)'s mean) -> real values [2.6, 2.0, 1.2, 2.2], mean
    2.0, not (2.6+2.0-200+1.2+2.2)/5 = -38.4."""
    adapter = QuantAdapter()
    claim = Claim(
        text="x", domain="quant",
        context={
            "dataset_path": str(air_quality_csv_path), "column": "CO(GT)", "stat": "mean",
            "expected_value": (2.6 + 2.0 + 1.2 + 2.2) / 4, "tolerance": 1e-9,
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "supports"
    assert "skipped_non_numeric=1" in ev[0].locator  # only CO(GT)'s own -200 row


async def test_air_quality_sentinel_excluded_from_correlation(air_quality_csv_path):
    """A -200 in EITHER column of the pair drops that row (same rule as
    NaN/Infinity) -- 2 of the 5 rows have a -200 somewhere, leaving 3
    real paired rows: (2.6,166), (2.0,103), (2.2,150)."""
    adapter = QuantAdapter()
    import statistics as _statistics

    expected = _statistics.correlation([2.6, 2.0, 2.2], [166, 103, 150])
    claim = Claim(
        text="x", domain="quant",
        context={
            "dataset_path": str(air_quality_csv_path), "column": "CO(GT)", "column_b": "NOx(GT)",
            "stat": "correlation", "expected_value": expected, "tolerance": 1e-9,
        },
    )
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "supports"
    assert "skipped_non_numeric=2" in ev[0].locator


async def test_minus_200_in_a_differently_named_file_is_not_treated_as_a_sentinel(csv_path):
    """The sentinel lookup is scoped to filenames in _DATASET_SENTINELS --
    a -200 in an UNRELATED file (this module's own generic csv_path fixture,
    named 'data.csv') must be treated as a real, literal reading, not
    silently guessed to be a missing-value marker it was never documented
    to be."""
    import csv as _csv

    path = csv_path.parent / "other.csv"
    with path.open("w", newline="") as f:
        writer = _csv.DictWriter(f, fieldnames=["value"])
        writer.writeheader()
        writer.writerow({"value": -200})
        writer.writerow({"value": 10})
    adapter = QuantAdapter()
    claim = Claim(
        text="x", domain="quant",
        context={"dataset_path": str(path), "column": "value", "stat": "mean", "expected_value": -95.0, "tolerance": 1e-9},
    )
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "supports"  # (-200 + 10) / 2 == -95.0 -- -200 counted as real


async def test_path_traversal_outside_allowed_directories_is_rejected():
    """FOUND BUG (external security review): dataset_path previously went
    straight into Path(...).open() with no containment check -- an
    arbitrary local file read via POST /verify, not just a "wrong file"
    bug. This path's STRING starts under the real evals/fixtures/
    allowlist entry, but ../ segments walk it all the way out to a real
    file (/etc/passwd) that is NOT under any allowed directory -- proving
    the check runs on the resolved real path, not a string prefix match."""
    adapter = QuantAdapter()
    traversal_path = "evals/fixtures/" + "../" * 12 + "etc/passwd"
    claim = Claim(
        text="x", domain="quant",
        context={"dataset_path": traversal_path, "column": "v", "stat": "mean", "expected_value": 1.0},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "not within an allowed directory" in gap[0].lower()


async def test_symlink_escaping_the_allowed_directory_is_rejected(tmp_path):
    """Same vulnerability class, the OTHER named vector: a symlink whose
    literal path lives inside an allowed directory (here, tmp_path itself,
    widened to "allowed" by this module's own autouse fixture) but whose
    REAL target resolves outside every allowed directory. Path.resolve()
    follows the symlink to its real target before the containment check
    runs, so the escape is caught the same way the ../ traversal is."""
    target_outside_everything = Path("/etc/passwd")
    assert target_outside_everything.is_file()  # only meaningful if the escape target is real
    symlink_path = tmp_path / "escape.csv"
    symlink_path.symlink_to(target_outside_everything)

    adapter = QuantAdapter()
    claim = Claim(
        text="x", domain="quant",
        context={"dataset_path": str(symlink_path), "column": "v", "stat": "mean", "expected_value": 1.0},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "not within an allowed directory" in gap[0].lower()


async def test_null_byte_in_path_is_a_clean_rejection_not_a_crash():
    """FOUND BUG (follow-up security review): a path with an embedded null
    byte makes Path.resolve() raise ValueError ("embedded null character"),
    not OSError -- only OSError was caught in is_path_within_allowed_dirs(),
    so this crashed instead of producing a clean, named gap."""
    adapter = QuantAdapter()
    claim = Claim(
        text="x", domain="quant",
        context={"dataset_path": "evals/fixtures/x\x00/../../../../etc/passwd", "column": "v", "stat": "mean", "expected_value": 1.0},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "not within an allowed directory" in gap[0].lower()


async def test_dataset_path_list_with_a_non_string_element_is_a_named_gap_not_a_crash():
    """FOUND BUG (follow-up security review): the list-shape check for
    dataset_path validated it's a list, but not that every element is a
    string -- Path(123) would crash downstream with a TypeError instead of
    a clean, named gap."""
    adapter = QuantAdapter()
    claim = Claim(
        text="x", domain="quant",
        context={"dataset_path": ["evals/fixtures/sample_measurements.csv", 123], "column": "voltage", "stat": "mean", "expected_value": 1.0},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "string" in gap[0].lower()


async def test_clean_column_with_zero_non_finite_values_is_unaffected(csv_path):
    """Regression guard: the fix must not change behavior on data that was
    already clean -- same fixture, same exact assertions as the original
    (pre-fix) mean test, still passing unchanged."""
    adapter = QuantAdapter()
    claim = Claim(
        text="mean voltage is 5.0", domain="quant",
        context={"dataset_path": str(csv_path), "column": "voltage", "stat": "mean",
                 "expected_value": 5.0, "tolerance": 0.01},
    )
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "supports"
    assert "rows=6" in ev[0].locator
    assert "skipped_non_numeric=1" in ev[0].locator  # the pre-existing "not_a_number" bad row only
