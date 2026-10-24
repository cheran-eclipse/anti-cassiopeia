"""
Phase B item 14 (external review): `stress_test/data/` is gitignored (see
`.gitignore`), so a fresh clone cannot run any `stress_test/` script at all
-- not a minor inconvenience, a real reproducibility gap for 30 files
across two domains. This script re-fetches every one of them from the
exact public URLs already recorded in `stress_test/PROVENANCE.md`, so a
fresh clone can regenerate byte-identical data with no credentials and no
manual steps:

    PYTHONPATH=. python stress_test/bootstrap_data.py

Verifies every output file's SHA-256 against `stress_test/data_checksums.txt`
(committed, NOT gitignored) and reports exactly which files matched,
differed, or errored -- it does not silently assume success. A checksum
mismatch is reported, not hidden, since an upstream file can legitimately
change after this script was written (UCI/GitHub content is not under this
project's control) -- see this file's own `--update-checksums` flag for
the one legitimate reason to accept a new value.

Does NOT fetch: `air_quality_shard1/2.csv`, `bike_sharing_shard1/2.csv`,
`gas_turbine_emission_shard1/2.csv` (not separately hosted anywhere --
generated here by splitting the already-fetched full file in half, same
split point as the originals: first `len(rows) // 2` data rows to shard1,
the rest to shard2, header duplicated in both) or the two `SYNTHETIC_*.rpt`
fpga fixtures (explicitly synthetic, already committed to git at
`evals/fixtures/`, just copied here unchanged -- not re-fetched from
anywhere since they were never fetched in the first place).
"""

from __future__ import annotations

import csv
import hashlib
import io
import shutil
import sys
from pathlib import Path
from urllib.request import urlopen

REPO_ROOT = Path(__file__).parent.parent
ML_DATA_DIR = REPO_ROOT / "stress_test/data/ml_data"
FPGA_DIR = REPO_ROOT / "stress_test/data/fpga_embedded"
CHECKSUMS_PATH = REPO_ROOT / "stress_test/data_checksums.txt"
TIMEOUT = 30

# --- ml_data: UCI static per-dataset CSV endpoint, no auth needed.
# (filename, UCI dataset id) -- see stress_test/PROVENANCE.md's own table
# for the human-readable dataset names/URLs this id list was read from.
_UCI_CSV_DATASETS = [
    ("air_quality.csv", 360),
    ("combined_cycle_power_plant.csv", 294),
    ("concrete_compressive_strength.csv", 165),
    ("wine_quality.csv", 186),
    ("appliances_energy_prediction.csv", 374),
    ("auto_mpg.csv", 9),
    ("abalone.csv", 1),
    ("forest_fires.csv", 162),
    ("bike_sharing.csv", 275),
    ("real_estate_valuation.csv", 477),
    ("airfoil_self_noise.csv", 291),
    ("gas_turbine_emission.csv", 551),
    ("superconductivity.csv", 464),
    ("parkinsons_telemonitoring.csv", 189),
]

# yacht_hydrodynamics.csv: the OLDER raw .data endpoint, whitespace-
# separated, NO header row -- column names are this project's own labels
# (see PROVENANCE.md), not UCI's, since UCI's page states no header.
_YACHT_URL = "https://archive.ics.uci.edu/ml/machine-learning-databases/00243/yacht_hydrodynamics.data"
_YACHT_COLUMNS = [
    "longitudinal_center_of_buoyancy", "prismatic_coefficient", "length_displacement_ratio",
    "beam_draught_ratio", "length_beam_ratio", "froude_number", "residuary_resistance",
]

# --- fpga_embedded: real files committed in OTHER people's public GitHub
# repos, found via `gh api search/code` (see PROVENANCE.md) -- refetched
# here over plain HTTPS via raw.githubusercontent.com (no `gh`/auth
# needed for a public repo's raw file content). (local filename, owner/repo, path)
_GITHUB_FPGA_FILES = [
    ("jiwoonl__timing.txt", "jiwoonl/Event-Driven-Spiking-Neural-Network-Accelerator-for-FPGA", "outputs/timing.txt"),
    ("dawsonjon__FPGA-TX__post_synth_timing_summary.rpt", "dawsonjon/FPGA-TX", "synthesis/nexys_4/tx/post_synth_timing_summary.rpt"),
    ("Nero7991__llm.vhdl__timing_summary_A.rpt", "Nero7991/llm.vhdl", "hw/jc/pinfinder/results/timing_summary_A.rpt"),
    ("Nero7991__llm.vhdl__timing_summary_B.rpt", "Nero7991/llm.vhdl", "hw/jc/pinfinder/results/timing_summary_B.rpt"),
    ("rbarzic__nanorv32__post_synth_timing_summary.rpt", "rbarzic/nanorv32", "synt/fpga/rpt/post_synth_timing_summary.rpt"),
    ("David-Durst__embeddedHaskellAetherling__timing_summary.txt", "David-Durst/embeddedHaskellAetherling", "pnr/exs/timing_summary.txt"),
    ("hdlguy__make_for_vivado__timing.rpt", "hdlguy/make_for_vivado", "implement/results/timing.rpt"),
    ("scarletnova20__Vision-In-Memory-System-On-RISCV__timing_impl.txt", "scarletnova20/Vision-In-Memory-System-On-RISCV", "reports/timing_impl.txt"),
    ("scarletnova20__Vision-In-Memory-System-On-RISCV__timing_synth.txt", "scarletnova20/Vision-In-Memory-System-On-RISCV", "reports/timing_synth.txt"),
    ("nethakah__nasdaq-pipeline__timing_route.rpt", "nethakah/nasdaq-pipeline", "fpga/results/timing_route.rpt"),
]

# Already-committed, explicitly-synthetic fixtures (never fetched from
# anywhere -- copied unchanged from evals/fixtures/, see PROVENANCE.md §fpga).
_SYNTHETIC_FPGA_COPIES = [
    ("SYNTHETIC_multi_corner.rpt", REPO_ROOT / "evals/fixtures/vivado_timing_report.rpt"),
    ("SYNTHETIC_single_corner.rpt", REPO_ROOT / "evals/fixtures/vivado_timing_report_single_corner.rpt"),
]

# (full file, shard1 name, shard2 name) -- same first-half/second-half
# split as the originals (confirmed by inspection: shard1 gets the first
# len(rows)//2 data rows, shard2 gets the rest, header duplicated in both).
_SHARD_SPECS = [
    ("air_quality.csv", "air_quality_shard1.csv", "air_quality_shard2.csv"),
    ("bike_sharing.csv", "bike_sharing_shard1.csv", "bike_sharing_shard2.csv"),
    ("gas_turbine_emission.csv", "gas_turbine_emission_shard1.csv", "gas_turbine_emission_shard2.csv"),
]


def _fetch(url: str) -> bytes:
    with urlopen(url, timeout=TIMEOUT) as resp:
        return resp.read()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_shard(full_path: Path, shard1_path: Path, shard2_path: Path) -> None:
    with full_path.open(newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    split = len(rows) // 2

    def write(path: Path, rows_subset: list[list[str]]) -> None:
        with path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows_subset)

    write(shard1_path, rows[:split])
    write(shard2_path, rows[split:])


def bootstrap() -> dict[str, str]:
    """Fetches/generates every file, returns {relative_path: sha256}."""
    ML_DATA_DIR.mkdir(parents=True, exist_ok=True)
    FPGA_DIR.mkdir(parents=True, exist_ok=True)
    results: dict[str, str] = {}
    errors: list[str] = []

    for filename, uci_id in _UCI_CSV_DATASETS:
        dest = ML_DATA_DIR / filename
        url = f"https://archive.ics.uci.edu/static/public/{uci_id}/data.csv"
        try:
            dest.write_bytes(_fetch(url))
            print(f"[ml_data] fetched {filename} (UCI id {uci_id})")
        except OSError as exc:
            errors.append(f"{filename}: fetch failed from {url}: {exc!r}")
            continue
        results[f"stress_test/data/ml_data/{filename}"] = _sha256(dest)

    try:
        raw = _fetch(_YACHT_URL).decode()
        dest = ML_DATA_DIR / "yacht_hydrodynamics.csv"
        with dest.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(_YACHT_COLUMNS)
            for line in raw.splitlines():
                if line.strip():
                    # float() round-trip (not the raw token strings) to match
                    # the original file's formatting exactly -- confirmed by
                    # diffing against the already-fetched file: it was written
                    # via float() too, so e.g. "0.150" in the raw source became
                    # "0.15" (same real value, no precision lost either way).
                    writer.writerow([float(tok) for tok in line.split()])
        print("[ml_data] fetched yacht_hydrodynamics.csv (UCI id 243, raw whitespace-delimited)")
        results["stress_test/data/ml_data/yacht_hydrodynamics.csv"] = _sha256(dest)
    except OSError as exc:
        errors.append(f"yacht_hydrodynamics.csv: fetch failed from {_YACHT_URL}: {exc!r}")

    for full_name, shard1_name, shard2_name in _SHARD_SPECS:
        full_path = ML_DATA_DIR / full_name
        if not full_path.exists():
            errors.append(f"{shard1_name}/{shard2_name}: can't generate, {full_name} is missing (fetch failed above?)")
            continue
        s1, s2 = ML_DATA_DIR / shard1_name, ML_DATA_DIR / shard2_name
        _write_shard(full_path, s1, s2)
        print(f"[ml_data] generated {shard1_name} + {shard2_name} (split from {full_name})")
        results[f"stress_test/data/ml_data/{shard1_name}"] = _sha256(s1)
        results[f"stress_test/data/ml_data/{shard2_name}"] = _sha256(s2)

    for filename, repo, path in _GITHUB_FPGA_FILES:
        dest = FPGA_DIR / filename
        url = f"https://raw.githubusercontent.com/{repo}/HEAD/{path}"
        try:
            dest.write_bytes(_fetch(url))
            print(f"[fpga_embedded] fetched {filename} ({repo})")
        except OSError as exc:
            errors.append(f"{filename}: fetch failed from {url}: {exc!r}")
            continue
        results[f"stress_test/data/fpga_embedded/{filename}"] = _sha256(dest)

    for filename, source_path in _SYNTHETIC_FPGA_COPIES:
        dest = FPGA_DIR / filename
        if not source_path.exists():
            errors.append(f"{filename}: source fixture missing at {source_path}")
            continue
        shutil.copyfile(source_path, dest)
        print(f"[fpga_embedded] copied {filename} (synthetic, from {source_path.relative_to(REPO_ROOT)})")
        results[f"stress_test/data/fpga_embedded/{filename}"] = _sha256(dest)

    if errors:
        print("\nErrors (file(s) not produced):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)

    return results


def _load_checksums() -> dict[str, str]:
    if not CHECKSUMS_PATH.exists():
        return {}
    out = {}
    for line in CHECKSUMS_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, rel_path = line.split(maxsplit=1)
        out[rel_path] = digest
    return out


def main() -> int:
    update = "--update-checksums" in sys.argv
    results = bootstrap()
    known = _load_checksums()

    mismatches = []
    new_files = []
    for rel_path, digest in sorted(results.items()):
        if rel_path not in known:
            new_files.append(rel_path)
        elif known[rel_path] != digest:
            mismatches.append(rel_path)

    if update:
        with CHECKSUMS_PATH.open("w") as f:
            f.write("# sha256  path -- generated by stress_test/bootstrap_data.py --update-checksums\n")
            for rel_path, digest in sorted(results.items()):
                f.write(f"{digest}  {rel_path}\n")
        print(f"\nWrote {len(results)} checksums to {CHECKSUMS_PATH.relative_to(REPO_ROOT)}.")
        return 0

    print(f"\n{len(results)} file(s) produced, checked against {CHECKSUMS_PATH.relative_to(REPO_ROOT)}:")
    if new_files:
        print(f"  {len(new_files)} file(s) have no recorded checksum yet (not necessarily wrong -- "
              "run with --update-checksums once you've reviewed them):")
        for p in new_files:
            print(f"    - {p}")
    if mismatches:
        print(f"  {len(mismatches)} file(s) DIFFER from the recorded checksum (upstream content may have "
              "changed since this project's stress-test numbers were computed -- re-running the stress "
              "test against these files may no longer reproduce the exact numbers in stress_test/results/):")
        for p in mismatches:
            print(f"    - {p}")
    if not new_files and not mismatches:
        print("  All match. Bootstrapped data is byte-identical to what this project's stress tests were run against.")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
