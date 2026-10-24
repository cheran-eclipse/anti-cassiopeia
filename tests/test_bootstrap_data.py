"""
Phase B item 14 (external review): stress_test/bootstrap_data.py exists to
close the "stress_test/data/ is gitignored and not reproducible from a
clean checkout" gap. These tests don't re-exercise the live network fetch
(already verified manually: see stress_test/PROVENANCE.md's own note,
confirmed byte-identical against the real committed checksums) -- they
check the two things that matter for CI without a network call: the
script's declared file list hasn't silently drifted from what's actually
on disk, and the pure shard-splitting helper is correct.
"""

import csv
from pathlib import Path

from stress_test.bootstrap_data import (
    _GITHUB_FPGA_FILES, _SHARD_SPECS, _SYNTHETIC_FPGA_COPIES, _UCI_CSV_DATASETS, _write_shard, REPO_ROOT,
)

_DATA_DIR = REPO_ROOT / "stress_test/data"


def _declared_filenames() -> set[str]:
    names = {name for name, _id in _UCI_CSV_DATASETS}
    names.add("yacht_hydrodynamics.csv")
    for full, s1, s2 in _SHARD_SPECS:
        names.update({s1, s2})
    names.update({name for name, _repo, _path in _GITHUB_FPGA_FILES})
    names.update({name for name, _src in _SYNTHETIC_FPGA_COPIES})
    return names


def test_bootstrap_scripts_declared_file_list_matches_what_is_actually_on_disk():
    """Guards against the list in bootstrap_data.py silently falling out of
    sync with reality (e.g. a new real file added to stress_test/data/ by
    hand, forgotten here -- which would make a fresh clone quietly end up
    missing a file the rest of the stress-test scripts expect)."""
    if not _DATA_DIR.exists():
        import pytest
        pytest.skip("stress_test/data/ not present in this checkout -- nothing to compare against")

    on_disk = {p.name for p in _DATA_DIR.rglob("*") if p.is_file()}
    declared = _declared_filenames()
    assert on_disk == declared, (
        f"on disk but not declared: {on_disk - declared}; declared but not on disk: {declared - on_disk}"
    )


def test_write_shard_splits_rows_in_half_with_header_duplicated_in_both(tmp_path):
    full = tmp_path / "full.csv"
    full.write_text("a,b\n1,2\n3,4\n5,6\n7,8\n9,10\n")  # 5 data rows
    s1, s2 = tmp_path / "s1.csv", tmp_path / "s2.csv"
    _write_shard(full, s1, s2)

    def read(p):
        with p.open(newline="") as f:
            return list(csv.reader(f))

    rows1, rows2 = read(s1), read(s2)
    assert rows1[0] == rows2[0] == ["a", "b"]
    assert rows1[1:] == [["1", "2"], ["3", "4"]]
    assert rows2[1:] == [["5", "6"], ["7", "8"], ["9", "10"]]
    # combined, every original data row appears exactly once, in order, nothing duplicated or dropped
    assert rows1[1:] + rows2[1:] == [["1", "2"], ["3", "4"], ["5", "6"], ["7", "8"], ["9", "10"]]


def test_write_shard_handles_an_even_row_count_without_dropping_or_duplicating_a_row(tmp_path):
    full = tmp_path / "full.csv"
    full.write_text("x\n1\n2\n3\n4\n")  # 4 data rows
    s1, s2 = tmp_path / "s1.csv", tmp_path / "s2.csv"
    _write_shard(full, s1, s2)

    def read(p):
        with p.open(newline="") as f:
            return list(csv.reader(f))[1:]

    rows1, rows2 = read(s1), read(s2)
    assert len(rows1) == len(rows2) == 2
    assert rows1 + rows2 == [["1"], ["2"], ["3"], ["4"]]
