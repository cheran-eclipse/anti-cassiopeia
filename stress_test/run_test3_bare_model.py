"""
Stress Test #3, variant 2 (bare model, re-run on Test #3's own claim
set): a THIN wrapper around run_test2_bare.py's ALREADY-BUILT
run_bare_batch() -- deliberately NOT a reimplementation. Test #2 already
measures "what if we skipped the whole pipeline and just asked
openai/gpt-oss-120b directly, no retrieval, no file access, no tools" on
its own 1,000-claim sample; this module exists only so Test #3's
orchestrator (run_test3.py) can run that SAME, unmodified baseline
against whatever claim set Test #3 happens to be scoring in a given
round (a stratified Test #2 subset today; a competitive-benchmark
round's hand-picked claims in the future -- see
claude/ANTI_CASSIOPEIA_COMPETITIVE_BENCHMARK_PROTOCOL.md), with its own
distinct results file so Test #2's and Test #3's rows for the "same"
baseline never collide or get confused about which run produced them.

Scope: unlike variant 3 (nebius-agent, robotics/research_web only --
ml_data/fpga_embedded are a byte-for-byte no-op for it), this variant
runs on ALL FOUR domains unfiltered, exactly as run_test2_bare.py
already designed it to -- for ml_data/fpga_embedded specifically, the
model has no way to see the real dataset/report file at all, so a
confident verdict there is only possible by fabrication, which
run_bare_batch()'s own `fabricated_detail` flag already names rather
than silently scoring on numeric luck. This is a MORE complete floor
than a propose-only-domains variant would be, and reusing it as-is
costs nothing extra to build.

COST NOTE (read before assuming "cheapest variant" means "free
variant"): this is still a REAL Nebius API call per claim -- one chat
completion to openai/gpt-oss-120b, with a real (small) token cost
tracked exactly like every other Nebius-billed variant via the SAME
shared UsageTracker/Nebius sub-cap run_test3.py already uses for
variant 3 (nebius-agent) and variant 4 (generic RAG). What's free here
is RETRIEVAL -- there is no search, no fetch, no chunking, no BM25, no
separate retrieval-cost line at all, because there is no retrieval
step. The one thing that costs money (the completion call itself) is
exactly as real and exactly as tracked as every other Nebius call in
this harness; see each row's own `cost_usd` for the actual number.
"""

from __future__ import annotations

import sys
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

from instrumented_client import BUDGET_HARD_STOP_USD, UsageTracker  # noqa: E402
from run_test2_bare import run_bare_batch  # noqa: E402

RAW_RESULTS_PATH = REPO_ROOT / "stress_test/results/test3_bare_model_raw.jsonl"
BUGS_PATH = REPO_ROOT / "stress_test/BUGS_FOUND.md"


async def run_bare_model_batch(
    claims: list[dict],
    tag: str,
    *,
    raw_results_path: Path = RAW_RESULTS_PATH,
    bugs_path: Path = BUGS_PATH,
    tracker: UsageTracker | None = None,
    budget_usd: float = BUDGET_HARD_STOP_USD,
) -> list[dict]:
    """Pure passthrough to run_test2_bare.run_bare_batch() -- the only
    thing this wrapper changes is WHERE results land (Test #3's own
    `test3_bare_model_raw.jsonl`, not Test #2's `test2_bare_raw.jsonl`)
    and the `[tag]` prefix on its printed lines, so Test #3 runs are
    never mistaken for Test #2 runs in either the raw files or the
    console output, even though the underlying logic is identical."""
    return await run_bare_batch(
        claims, tag=f"test3-{tag}", raw_results_path=raw_results_path, bugs_path=bugs_path,
        tracker=tracker, budget_usd=budget_usd,
    )
