"""
Stress Test #3, variant 3: "Nebius-agent" baseline.

Reuses the REAL production retrieval exactly as robotics.py/research_web.py
run it (same chunking, same BM25 index, same domain-tuned retrieval
queries, same propose() call against the same model) but skips
verify_proposal() -- propose()'s raw output becomes the final evidence
with NO independent re-check that the quote actually appears in the
source chunk. Isolates the value of the VERIFY step specifically,
holding retrieval quality constant (same retrieval as variant 1, the
real pipeline, and variant 2 has none at all).

HOW: a runtime monkeypatch of the `verify_proposal` name inside
anticassiopeia.domains.robotics and anticassiopeia.domains.research_web,
scoped to this script's own process and restored afterward. This writes
nothing to disk and leaves anticassiopeia/ completely unmodified -- it's
read-only use of that package, exercised through Python's normal
late-binding name lookup instead of a constructor injection point
(unlike the LLM client, robotics.py/research_web.py have no injection
point for swapping the verify step out, so this is the equivalent
substitution at the only seam that exists).

ml_data/fpga_embedded never call propose()/verify_proposal() at all --
for those two domains this variant is byte-for-byte the same code path
as variant 1 (the real pipeline), so their results are COPIED from
Test #2's already-measured pipeline raw results, not meaninglessly
rerun (see stress_test/run_test3.py's orchestration).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

# FOUND BUG (external review, 2026-10-25): this script constructs a real
# ResearchWebAdapter (directly or via run_test1.build_engine), whose
# research_web.py _tavily_search() reads os.environ.get("TAVILY_API_KEY")
# directly -- NOT dotenv_values(). Every script in this directory loaded
# secrets via dotenv_values(".env") for ITS OWN direct provider calls
# (Perplexity/Tavily/Gemini) without ever populating the real process
# environment -- so Tavily (research_web.py's PRIMARY search backend) has
# been silently returning [] (missing key -> empty list, by that
# function's own documented contract) in every prior run of this
# project's stress-test history, falling back to the much weaker DDG/
# Wikipedia backends every time. The real production server
# (api/server.py) was never affected -- it already calls
# load_dotenv(override=False) at import time. Fixed at the source here:
# load it into the real environment before anything downstream reads it.
from dotenv import load_dotenv  # noqa: E402
load_dotenv(REPO_ROOT / ".env", override=False)

import json  # noqa: E402

import anticassiopeia.domains.research_web as research_web_mod  # noqa: E402
import anticassiopeia.domains.robotics as robotics_mod  # noqa: E402
from anticassiopeia.core.verdict import Claim, Evidence  # noqa: E402
from anticassiopeia.retrieval.verify import VerificationResult  # noqa: E402
from instrumented_client import BUDGET_HARD_STOP_USD, BudgetExceededError, UsageTracker  # noqa: E402
from run_test1 import build_engine, classify, locked_append  # noqa: E402

RAW_RESULTS_PATH = REPO_ROOT / "stress_test/results/test3_nebius_agent_raw.jsonl"
BUGS_PATH = REPO_ROOT / "stress_test/BUGS_FOUND.md"

_PROPOSE_ONLY_DOMAINS = {"robotics", "research_web"}


def _unverified_accept(proposal, chunks_by_id, *, source, stance, trust=0.8):
    """Stands in for retrieval.verify.verify_proposal(): always accepts,
    never checks the quote against the real chunk text. The whole point
    of this variant is measuring what happens when that check is
    skipped, so this function performs no check at all -- not even the
    chunk_id existence check, matching "take propose()'s raw output as
    the final verdict" literally."""
    chunk = chunks_by_id.get(proposal.chunk_id)
    doc_id = chunk.doc_id if chunk is not None else source
    locator = (
        f"{doc_id}, chunk {proposal.chunk_id} (UNVERIFIED -- quote NOT independently "
        f"re-checked against source text; Nebius-agent baseline, stress_test/ only)"
    )
    snippet = proposal.quote
    if proposal.value is not None:
        snippet = f"{snippet} (value={proposal.value!r}, unit={proposal.unit!r}, kind={proposal.kind!r})"
    evidence = Evidence(source=source, snippet=snippet, stance=stance, trust=trust, locator=locator)
    return VerificationResult(
        accepted=True,
        reason="UNVERIFIED: proposer's claim trusted without an independent re-check (Nebius-agent baseline).",
        evidence=evidence,
    )


class _patched_verify:
    """Context manager: monkeypatches verify_proposal in both modules for
    its duration, restores the real functions on exit (even on error)."""

    def __enter__(self):
        self._orig_robotics = robotics_mod.verify_proposal
        self._orig_research_web = research_web_mod.verify_proposal
        robotics_mod.verify_proposal = _unverified_accept
        research_web_mod.verify_proposal = _unverified_accept
        return self

    def __exit__(self, *exc_info):
        robotics_mod.verify_proposal = self._orig_robotics
        research_web_mod.verify_proposal = self._orig_research_web
        return False


async def run_nebius_agent_batch(
    claims: list[dict],
    tag: str,
    *,
    raw_results_path: Path = RAW_RESULTS_PATH,
    bugs_path: Path = BUGS_PATH,
    tracker: UsageTracker | None = None,
    budget_usd: float = BUDGET_HARD_STOP_USD,
) -> list[dict]:
    """Only claims in _PROPOSE_ONLY_DOMAINS should be passed in here --
    ml_data/fpga_embedded claims are a no-op for this variant and belong
    to the orchestrator's copy-from-Test#2 path instead."""
    propose_claims = [c for c in claims if c["domain"] in _PROPOSE_ONLY_DOMAINS]
    skipped = len(claims) - len(propose_claims)
    if skipped:
        print(f"[{tag}] (nebius-agent) skipping {skipped} ml_data/fpga_embedded claim(s) -- "
              f"identical to the pipeline for those domains, copied instead, not rerun.")

    tracker = tracker if tracker is not None else UsageTracker()
    raw_results_path.parent.mkdir(parents=True, exist_ok=True)

    with _patched_verify():
        engine = await build_engine(tracker, budget_usd=budget_usd)

        bugs_found: list[dict] = []
        results = []
        try:
            for c in propose_claims:
                tracker.set_domain(c["domain"])
                before = tracker.snapshot()
                claim = Claim(**c["claim_payload"])

                start = time.monotonic()
                error = None
                try:
                    verdict = await engine.verify(claim)
                    predicted = verdict.state.value
                except BudgetExceededError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    predicted = "CRASH"
                    error = f"{type(exc).__name__}: {exc}"
                latency = time.monotonic() - start

                after = tracker.snapshot()
                delta_cost = after["total_cost_usd"] - before["total_cost_usd"]

                severity = "crash" if predicted == "CRASH" else classify(predicted, c["ground_truth_verdict"])

                record = {
                    "claim_id": c["claim_id"],
                    "domain": c["domain"],
                    "tier": c["tier"],
                    "predicted_verdict": predicted,
                    "ground_truth_verdict": c["ground_truth_verdict"],
                    "severity": severity,
                    "latency_s": latency,
                    "cost_usd": delta_cost,
                    "error": error,
                }
                results.append(record)
                locked_append(raw_results_path, json.dumps(record) + "\n")

                if severity in ("dangerous", "crash"):
                    bugs_found.append({**record, "claim_payload": c["claim_payload"]})

                print(
                    f"[{tag}] (nebius-agent) {c['claim_id']:28s} domain={c['domain']:14s} tier={c['tier']} "
                    f"predicted={predicted:13s} truth={c['ground_truth_verdict']:13s} "
                    f"severity={severity:17s} latency={latency:.2f}s cost=${delta_cost:.6f}"
                )
        except BudgetExceededError as exc:
            print(f"\nBUDGET HARD STOP (nebius-agent): {exc}")

    if bugs_found:
        # A dangerous result here means "the real retrieval found something, but
        # trusting it unverified led to a wrong verdict" -- this is NOT automatically
        # a production bug (anticassiopeia/ always verifies for real); it's exactly
        # the finding this variant exists to surface, recorded as its own tagged
        # section so it is never confused with an actual pipeline bug.
        chunk_lines = [f"\n## Test #3 nebius-agent batch `{tag}` — {len(bugs_found)} dangerous/crash result(s) "
                        f"(isolates the value of skipping verify_proposal(); not a pipeline bug)\n\n"]
        for b in bugs_found:
            chunk_lines.append(f"### {b['claim_id']} ({b['domain']}, tier {b['tier']})\n")
            chunk_lines.append(f"- Claim: `{json.dumps(b['claim_payload'])}`\n")
            chunk_lines.append(f"- Nebius-agent (no verify) predicted: **{b['predicted_verdict']}**, "
                                f"ground truth: **{b['ground_truth_verdict']}** ({b['severity']})\n")
            if b["error"]:
                chunk_lines.append(f"- Error: `{b['error']}`\n")
            chunk_lines.append("\n")
        locked_append(bugs_path, "".join(chunk_lines))

    return results
