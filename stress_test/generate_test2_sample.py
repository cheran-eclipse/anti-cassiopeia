"""
Stress Test #2, Part A: free, local, no API calls. Picks a stratified
~1,000-claim subset of the EXISTING stress_test/claims/manifest.jsonl
(3,311 claims, already generated and ground-truth-labeled by Test #1 —
nothing regenerated here) whose per-(domain, tier) composition mirrors
the full manifest's, and writes a pointer file (claim IDs only, not a
copy of claim_payload/ground_truth) to stress_test/claims/test2_sample.jsonl.

Deterministic: a seeded RNG, so re-running this script reproduces the
exact same sample.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
MANIFEST_PATH = REPO_ROOT / "stress_test/claims/manifest.jsonl"
SAMPLE_PATH = REPO_ROOT / "stress_test/claims/test2_sample.jsonl"

TARGET_TOTAL = 1000
SEED = 20261018


def load_manifest() -> list[dict]:
    rows = []
    with open(MANIFEST_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def stratified_sample(rows: list[dict], target_total: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    by_stratum: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for r in rows:
        by_stratum[(r["domain"], r["tier"])].append(r)

    total = len(rows)
    # Largest-remainder method so per-stratum sample counts sum to exactly
    # target_total while staying proportional to each stratum's real share.
    raw_counts = {k: len(v) / total * target_total for k, v in by_stratum.items()}
    floor_counts = {k: int(v) for k, v in raw_counts.items()}
    remainder = target_total - sum(floor_counts.values())
    remainders = sorted(by_stratum, key=lambda k: raw_counts[k] - floor_counts[k], reverse=True)
    for k in remainders[:remainder]:
        floor_counts[k] += 1

    sample = []
    for k, n in floor_counts.items():
        pool = by_stratum[k][:]
        rng.shuffle(pool)
        sample.extend(pool[:n])
    rng.shuffle(sample)
    return sample


def main() -> None:
    rows = load_manifest()
    sample = stratified_sample(rows, TARGET_TOTAL, SEED)

    SAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SAMPLE_PATH, "w") as f:
        for r in sample:
            f.write(json.dumps({"claim_id": r["claim_id"], "domain": r["domain"], "tier": r["tier"]}) + "\n")

    print(f"Full manifest: {len(rows)} claims. Sample: {len(sample)} claims.\n")
    print("Composition check (sample %% vs full manifest %%):")
    full_counts: dict[tuple[str, int], int] = defaultdict(int)
    for r in rows:
        full_counts[(r["domain"], r["tier"])] += 1
    sample_counts: dict[tuple[str, int], int] = defaultdict(int)
    for r in sample:
        sample_counts[(r["domain"], r["tier"])] += 1
    for k in sorted(full_counts):
        full_pct = 100 * full_counts[k] / len(rows)
        sample_pct = 100 * sample_counts.get(k, 0) / len(sample)
        print(f"  {k}: full={full_counts[k]:5d} ({full_pct:5.2f}%)  sample={sample_counts.get(k, 0):4d} ({sample_pct:5.2f}%)")


if __name__ == "__main__":
    main()
