"""
Stress Test #3, variant 6: Tavily (live web search) + Gemini (plain
generation) as a manually-wired "frontier model + live web search"
competitor -- this replaces a direct Gemini-grounding-with-Google-Search
variant, which is blocked at the account level (confirmed live: every
model and every tool-name spelling tried returns
429 RESOURCE_EXHAUSTED the instant the google_search tool is attached,
while the SAME models return 200 for plain generation -- consistent
with Google gating search-grounding behind Cloud billing separately
from the free generation tier; see TEST3_REPORT.md's "known limitations"
section for the exact confirmation and the official pricing-page
citation for grounding's $14/1,000-request fee, which this project's
API key evidently cannot reach at all).

Two sequential, separately-costed steps per claim:
1. Tavily Search API (`POST https://api.tavily.com/search`) with the raw
   claim text as the query -- real retrieval, no domain tuning.
2. One Gemini completion fed Tavily's top results as context, asked the
   same confirmed/contradicted/undetermined question every other
   variant uses. Plain generation only -- NOT the grounding tool, since
   that's the capability this variant exists to work around.

MODEL CHOICE, found the hard way: the pilot's FIRST attempt used
`gemini-flash-latest` (resolved live to `gemini-3.8-flash`) and hit a
real external wall mid-pilot -- confirmed from the live error body:
`generate_content_free_tier_requests` is capped at **20 requests per
day** for that model on this key's free tier (`quotaId:
GenerateRequestsPerDayPerProjectPerModel-FreeTier`, `quotaValue: "20"`),
plus one transient 503 "high demand" on top. 15 of 28 pilot claims
CRASHed on that first attempt -- recorded honestly in the raw results
and in BUGS_FOUND.md rather than hidden. Switched to
`gemini-flash-lite-latest` (resolves live to `gemini-3.5-flash-lite`,
confirmed via a live call's `modelVersion` field), which has its own,
separate quota bucket and ran the full pilot without a single quota
error. This is now the model this module actually uses.

COST: Tavily's Search API does not return a dollar cost in its response
(it bills in flat per-call "credits", standard across result counts) --
tracked here as a call count against this project's already-provisioned
free Researcher-tier credits, NOT a dollar figure, and NOT counted
against the $20 Nebius cap (Tavily isn't Nebius). Gemini's cost IS
computed in real dollars from the live response's `usageMetadata`
token counts against Gemini 3.5 Flash-Lite's official published
Standard-tier pricing confirmed from
https://ai.google.dev/gemini-api/docs/pricing on 2026-10-18: $0.30/M
input tokens, $2.50/M output tokens (output price explicitly includes
thinking tokens per that page's own column header, though this model's
real responses showed zero thinking tokens in practice). This is real
money on a separate provider from Nebius, tracked and reported on its
own, not folded into the $20 Nebius cap or Perplexity/Tavily's
free-credit figures.
"""

from __future__ import annotations

import re
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

import httpx  # noqa: E402
from dotenv import dotenv_values  # noqa: E402

from run_test1 import classify, locked_append  # noqa: E402
from run_test2_bare import is_fabricated_detail  # noqa: E402

RAW_RESULTS_PATH = REPO_ROOT / "stress_test/results/test3_tavily_gemini_raw.jsonl"
BUGS_PATH = REPO_ROOT / "stress_test/BUGS_FOUND.md"

_ENV = dotenv_values(".env")
_TAVILY_ENDPOINT = "https://api.tavily.com/search"
_GEMINI_MODEL = "gemini-flash-lite-latest"
_GEMINI_ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{_GEMINI_MODEL}:generateContent"
_TIMEOUT = 30.0

# Gemini 3.5 Flash-Lite, Standard tier, Paid -- confirmed verbatim from the
# official pricing page on 2026-10-18.
_GEMINI_INPUT_COST_PER_M = 0.30
_GEMINI_OUTPUT_COST_PER_M = 2.50  # output price INCLUDES thinking tokens, per the page's own column header

_CANONICAL_WORDS = ("confirmed", "contradicted", "undetermined")


class TavilyGeminiError(Exception):
    pass


class GeminiQuotaExhausted(TavilyGeminiError):
    """Raised specifically when Gemini's error body says RESOURCE_EXHAUSTED --
    distinct from a generic failure so the batch loop can circuit-break
    instead of burning Tavily credits on a long, uninformative CRASH tail
    once the day's free-tier quota is actually gone (found the hard way in
    this test's own pilot: 15/28 claims crashed before this breaker existed)."""


def parse_verdict(text: str) -> str:
    t = text.lower()
    positions = {}
    for word in _CANONICAL_WORDS:
        m = re.search(rf"\b{word}\b", t)
        if m:
            positions[word] = m.start()
    if positions:
        return min(positions, key=positions.get)
    return "unparseable"


async def _tavily_search(query: str) -> tuple[str, int]:
    api_key = _ENV.get("TAVILY_API_KEY")
    if not api_key:
        raise TavilyGeminiError("TAVILY_API_KEY not loaded from .env via dotenv_values().")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            _TAVILY_ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"query": query, "max_results": 5},
        )
    if resp.status_code != 200:
        raise TavilyGeminiError(f"Tavily returned {resp.status_code}: {resp.text}")
    data = resp.json()
    results = data.get("results", [])
    context = "\n---\n".join(
        f"{r.get('title', '')} ({r.get('url', '')}): {r.get('content', '')}" for r in results
    )
    return context, len(results)


async def _gemini_complete(prompt: str) -> tuple[str, float, int, int]:
    api_key = _ENV.get("GEMINI_API_KEY")
    if not api_key:
        raise TavilyGeminiError("GEMINI_API_KEY not loaded from .env via dotenv_values().")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            _GEMINI_ENDPOINT,
            params={"key": api_key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
        )
    if resp.status_code != 200:
        if resp.status_code == 429 and "RESOURCE_EXHAUSTED" in resp.text:
            raise GeminiQuotaExhausted(f"Gemini returned {resp.status_code}: {resp.text}")
        raise TavilyGeminiError(f"Gemini returned {resp.status_code}: {resp.text}")
    data = resp.json()
    try:
        text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError, TypeError) as exc:
        raise TavilyGeminiError(f"Unexpected response shape from Gemini: {data}") from exc
    usage = data.get("usageMetadata", {})
    prompt_tokens = usage.get("promptTokenCount", 0)
    # Billed output = visible output + thinking tokens, per the pricing page's own
    # "Output price (including thinking tokens)" column header -- confirmed by
    # promptTokenCount + candidatesTokenCount + thoughtsTokenCount == totalTokenCount
    # in a real live response checked before writing this.
    output_tokens = usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)
    cost = (prompt_tokens / 1e6) * _GEMINI_INPUT_COST_PER_M + (output_tokens / 1e6) * _GEMINI_OUTPUT_COST_PER_M
    return text, cost, prompt_tokens, output_tokens


def _build_prompt(claim_text: str, context: str) -> str:
    return (
        f"Context from a live web search:\n{context[:4000]}\n\n"
        f"Is the following true: {claim_text}? Answer confirmed, contradicted, or undetermined, "
        f"and explain why in one sentence, based on the context above."
    )


async def run_tavily_gemini_batch(
    claims: list[dict],
    tag: str,
    *,
    raw_results_path: Path = RAW_RESULTS_PATH,
    bugs_path: Path = BUGS_PATH,
) -> list[dict]:
    raw_results_path.parent.mkdir(parents=True, exist_ok=True)

    total_gemini_cost = 0.0
    tavily_call_count = 0
    consecutive_quota_failures = 0
    _QUOTA_BREAKER_THRESHOLD = 2
    quota_exhausted_for_rest_of_batch = False
    bugs_found: list[dict] = []
    results = []
    for c in claims:
        claim_text = c["claim_payload"]["text"]

        error = None
        response_text = ""
        gemini_cost = 0.0
        n_tavily_results = 0
        start = time.monotonic()
        tavily_latency = 0.0
        gemini_latency = 0.0

        if quota_exhausted_for_rest_of_batch:
            # Circuit open: Gemini's free-tier quota is confirmed gone for today --
            # skip the Tavily call too (it would be wasted) rather than spend a
            # credit on every remaining claim for a Gemini call we already know fails.
            predicted = "SKIPPED_QUOTA"
            error = "Skipped: Gemini free-tier quota confirmed exhausted earlier in this batch."
        else:
            try:
                t0 = time.monotonic()
                context, n_tavily_results = await _tavily_search(claim_text)
                tavily_latency = time.monotonic() - t0
                tavily_call_count += 1

                t1 = time.monotonic()
                prompt = _build_prompt(claim_text, context)
                response_text, gemini_cost, _ptoks, _otoks = await _gemini_complete(prompt)
                gemini_latency = time.monotonic() - t1
                predicted = parse_verdict(response_text)
                consecutive_quota_failures = 0
            except GeminiQuotaExhausted as exc:
                predicted = "CRASH"
                error = f"{type(exc).__name__}: {exc}"
                consecutive_quota_failures += 1
                if consecutive_quota_failures >= _QUOTA_BREAKER_THRESHOLD:
                    quota_exhausted_for_rest_of_batch = True
                    print(f"\n[{tag}] (tavily+gemini) CIRCUIT BREAKER: {consecutive_quota_failures} consecutive "
                          f"Gemini quota-exhaustion errors -- skipping Gemini (and Tavily) for all remaining "
                          f"claims in this batch rather than burning calls on a guaranteed-fail tail.\n")
            except Exception as exc:  # noqa: BLE001
                predicted = "CRASH"
                error = f"{type(exc).__name__}: {exc}"
        latency = time.monotonic() - start
        total_gemini_cost += gemini_cost

        if predicted == "SKIPPED_QUOTA":
            severity = "skipped"
        elif predicted == "CRASH":
            severity = "crash"
        else:
            severity = classify(predicted, c["ground_truth_verdict"])
        fabricated = (
            False if predicted in ("CRASH", "SKIPPED_QUOTA")
            else is_fabricated_detail(c["domain"], predicted, response_text)
        )

        record = {
            "claim_id": c["claim_id"],
            "domain": c["domain"],
            "tier": c["tier"],
            "predicted_verdict": predicted,
            "ground_truth_verdict": c["ground_truth_verdict"],
            "severity": severity,
            "fabricated_detail": fabricated,
            "latency_s": latency,
            "tavily_latency_s": tavily_latency,
            "gemini_latency_s": gemini_latency,
            "n_tavily_results": n_tavily_results,
            "gemini_cost_usd": gemini_cost,
            "response_text": response_text,
            "error": error,
        }
        results.append(record)
        locked_append(raw_results_path, json.dumps(record) + "\n")

        if severity in ("dangerous", "crash"):
            bugs_found.append({**record, "claim_payload": c["claim_payload"]})

        print(
            f"[{tag}] (tavily+gemini) {c['claim_id']:28s} domain={c['domain']:14s} tier={c['tier']} "
            f"predicted={predicted:13s} truth={c['ground_truth_verdict']:13s} "
            f"severity={severity:17s} fab={fabricated!s:5s} latency={latency:.2f}s "
            f"(tavily={tavily_latency:.2f}s gemini={gemini_latency:.2f}s) gemini_cost=${gemini_cost:.6f}"
        )

    if bugs_found:
        chunk_lines = [f"\n## Test #3 Tavily+Gemini batch `{tag}` — {len(bugs_found)} dangerous/crash result(s) "
                        f"(external API baseline; not a pipeline bug)\n\n"]
        for b in bugs_found:
            chunk_lines.append(f"### {b['claim_id']} ({b['domain']}, tier {b['tier']})\n")
            chunk_lines.append(f"- Claim: `{json.dumps(b['claim_payload'])}`\n")
            chunk_lines.append(f"- Tavily+Gemini predicted: **{b['predicted_verdict']}**, "
                                f"ground truth: **{b['ground_truth_verdict']}** ({b['severity']})\n")
            if b["error"]:
                chunk_lines.append(f"- Error: `{b['error']}`\n")
            chunk_lines.append("\n")
        locked_append(bugs_path, "".join(chunk_lines))

    print(f"\n=== {tag} (tavily+gemini): {tavily_call_count} Tavily call(s) (free-credit, no $ figure), "
          f"Gemini total cost ${total_gemini_cost:.6f} ===")
    return results
