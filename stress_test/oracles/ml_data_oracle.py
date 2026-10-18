"""
Independent ground-truth oracle for ml_data claims.

Deliberately does NOT import anticassiopeia.domains.ml_data or any of its
helpers — an oracle that shares code with the adapter under test can share
its bugs too, and would never be able to catch one. Reads CSVs via
csv.reader + column INDEX (production uses csv.DictReader + column NAME)
and computes statistics with a from-scratch implementation (production
uses Python's `statistics` module) — two independently-written code paths
computing the same real numbers, not one path trusted twice.
"""

from __future__ import annotations

import csv
import math


def read_columns(paths: list[str]) -> tuple[list[str], list[list[float | None]]]:
    """Returns (header, rows) where each row is a list of float-or-None
    (None where a cell wasn't numeric), aligned across all given files
    (files are assumed to share the same header; raises if they don't)."""
    header: list[str] | None = None
    rows: list[list[float | None]] = []
    for p in paths:
        with open(p, newline="") as f:
            reader = csv.reader(f)
            this_header = next(reader)
            if header is None:
                header = this_header
            elif this_header != header:
                raise ValueError(f"{p}: header {this_header} does not match {paths[0]}'s header {header}")
            for row in reader:
                parsed: list[float | None] = []
                for cell in row:
                    try:
                        value = float(cell)
                    except ValueError:
                        parsed.append(None)
                        continue
                    # float() happily parses the literal strings "nan"/"inf"/"-inf"
                    # into real IEEE NaN/Infinity -- confirmed for real on UCI's own
                    # auto_mpg.csv, which spells 6 missing horsepower readings as the
                    # literal string "NaN" (not "?", not empty). A non-finite value
                    # is not a usable numeric reading; treated as missing here, same
                    # as an empty cell -- this is what a correct oracle does, and
                    # exposed that anticassiopeia/domains/ml_data.py does NOT do this
                    # (see stress_test/BUGS_FOUND.md).
                    parsed.append(value if math.isfinite(value) else None)
                rows.append(parsed)
    return header or [], rows


def column_values(header: list[str], rows: list[list[float | None]], column: str) -> list[float]:
    idx = header.index(column)  # raises ValueError if absent -- caller's problem to handle
    return [row[idx] for row in rows if idx < len(row) and row[idx] is not None]


def oracle_mean(values: list[float]) -> float:
    return sum(values) / len(values)


def oracle_stdev(values: list[float]) -> float:
    n = len(values)
    m = oracle_mean(values)
    variance = sum((v - m) ** 2 for v in values) / (n - 1)  # sample stdev, matches statistics.stdev
    return math.sqrt(variance)


def oracle_median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def _oracle_quantile(values: list[float], q: float) -> float:
    """Linear-interpolation quantile (same convention as statistics.quantiles'
    default 'exclusive' method), reimplemented from scratch rather than
    calling statistics.quantiles."""
    s = sorted(values)
    n = len(s)
    pos = q * (n + 1)
    lo = math.floor(pos)
    frac = pos - lo
    if lo < 1:
        return s[0]
    if lo >= n:
        return s[-1]
    return s[lo - 1] + frac * (s[lo] - s[lo - 1])


def oracle_p25(values: list[float]) -> float:
    return _oracle_quantile(values, 0.25)


def oracle_p75(values: list[float]) -> float:
    return _oracle_quantile(values, 0.75)


def oracle_correlation(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    mx, my = oracle_mean(xs), oracle_mean(ys)
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return cov / (sx * sy)


_ORACLE_FUNCS = {
    "mean": oracle_mean,
    "min": min,
    "max": max,
    "stdev": oracle_stdev,
    "median": oracle_median,
    "p25": oracle_p25,
    "p75": oracle_p75,
}


def compute(paths: list[str], stat: str, column: str, column_b: str | None = None) -> float:
    header, rows = read_columns(paths)
    if stat == "correlation":
        idx_a, idx_b = header.index(column), header.index(column_b)
        xs, ys = [], []
        for row in rows:
            if idx_a < len(row) and idx_b < len(row) and row[idx_a] is not None and row[idx_b] is not None:
                xs.append(row[idx_a])
                ys.append(row[idx_b])
        return oracle_correlation(xs, ys)
    values = column_values(header, rows, column)
    return _ORACLE_FUNCS[stat](values)


if __name__ == "__main__":
    # Smoke-test against the project's own existing fixture, independently.
    h, r = read_columns(["evals/fixtures/sample_measurements.csv"])
    v = column_values(h, r, "voltage")
    print("voltage mean (oracle):", oracle_mean(v))
    print("voltage stdev (oracle):", oracle_stdev(v))
    assert abs(oracle_mean(v) - 5.0) < 1e-9
