"""
Stress Test #3, variant 5: Perplexity's cited-answer API as an external
competitor baseline.

Endpoint confirmed live before writing this (the old, widely-documented
`/chat/completions` "Sonar" route returns HTTP 403 "Sonar is now the
Agent API. Use /v1/responses instead" as of this test): the CURRENT
endpoint is `POST https://api.perplexity.ai/v1/responses` with
`model: "perplexity/sonar"`. Confirmed live with a real call before
writing this module -- "sonar", "sonar-pro" and the old
"llama-3.1-sonar-*-online" model names all return 400 "not supported"
under this endpoint; "perplexity/sonar" is the one that actually works.

OUTPUT MAPPING (documented explicitly per this test's methodology rule):
- Perplexity's Agent API returns the answer as
  `output[0].content[0].text` (plain prose, markdown-formatted), NOT a
  separate `citations` array the way the old Sonar API used to --
  confirmed live: citations come back INLINED as markdown links
  (`[text](url)`) inside that same text. This module extracts them with
  a markdown-link regex purely for the record (so a human reading the
  raw results can see what Perplexity cited); extracted links are NOT
  used for scoring, verification, or anything beyond that record.
- The verdict is parsed from the same three canonical words
  (confirmed/contradicted/undetermined) every other variant in this
  project's test harness looks for, reusing run_test2_bare's parser so
  parsing is identical across variants.
- Cost comes directly from the response's own `usage.cost.total_cost`
  field (real, per-call, in USD) -- not estimated from a separately
  looked-up price list. This is real money from Perplexity's own
  already-provisioned credits, tracked here but NOT counted against
  this project's separate $20 Nebius cap.
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
from run_test2_bare import build_prompt, is_fabricated_detail  # noqa: E402

RAW_RESULTS_PATH = REPO_ROOT / "stress_test/results/test3_perplexity_raw.jsonl"
BUGS_PATH = REPO_ROOT / "stress_test/BUGS_FOUND.md"

_ENV = dotenv_values(".env")
_ENDPOINT = "https://api.perplexity.ai/v1/responses"
_MODEL = "perplexity/sonar"
_TIMEOUT = 60.0

_CANONICAL_WORDS = ("confirmed", "contradicted", "undetermined")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^\s)]+)\)")


class PerplexityError(Exception):
    pass


def extract_markdown_citations(text: str) -> list[str]:
    return [url for _label, url in _MD_LINK_RE.findall(text)]


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


async def _call_perplexity(prompt: str) -> tuple[str, float]:
    api_key = _ENV.get("PERPLEXITY_API_KEY")
    if not api_key:
        raise PerplexityError("PERPLEXITY_API_KEY not loaded from .env via dotenv_values().")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            _ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": _MODEL, "input": prompt},
        )
    if resp.status_code != 200:
        raise PerplexityError(f"Perplexity returned {resp.status_code}: {resp.text}")
    data = resp.json()
    try:
        text = "".join(
            part["text"] for item in data["output"] for part in item.get("content", []) if part.get("type") == "output_text"
        )
    except (KeyError, IndexError, TypeError) as exc:
        raise PerplexityError(f"Unexpected response shape from Perplexity: {data}") from exc
    cost = data.get("usage", {}).get("cost", {}).get("total_cost", 0.0)
    return text, cost


async def run_perplexity_batch(
    claims: list[dict],
    tag: str,
    *,
    raw_results_path: Path = RAW_RESULTS_PATH,
    bugs_path: Path = BUGS_PATH,
) -> list[dict]:
    raw_results_path.parent.mkdir(parents=True, exist_ok=True)

    total_cost = 0.0
    bugs_found: list[dict] = []
    results = []
    for c in claims:
        prompt = build_prompt(c["claim_payload"]["text"])

        start = time.monotonic()
        error = None
        response_text = ""
        cost = 0.0
        try:
            response_text, cost = await _call_perplexity(prompt)
            predicted = parse_verdict(response_text)
        except Exception as exc:  # noqa: BLE001
            predicted = "CRASH"
            error = f"{type(exc).__name__}: {exc}"
        latency = time.monotonic() - start
        total_cost += cost

        severity = "crash" if predicted == "CRASH" else classify(predicted, c["ground_truth_verdict"])
        fabricated = False if predicted == "CRASH" else is_fabricated_detail(c["domain"], predicted, response_text)
        citations = [] if predicted == "CRASH" else extract_markdown_citations(response_text)

        record = {
            "claim_id": c["claim_id"],
            "domain": c["domain"],
            "tier": c["tier"],
            "predicted_verdict": predicted,
            "ground_truth_verdict": c["ground_truth_verdict"],
            "severity": severity,
            "fabricated_detail": fabricated,
            "latency_s": latency,
            "cost_usd": cost,
            "citations": citations,
            "response_text": response_text,
            "error": error,
        }
        results.append(record)
        locked_append(raw_results_path, json.dumps(record) + "\n")

        if severity in ("dangerous", "crash"):
            bugs_found.append({**record, "claim_payload": c["claim_payload"]})

        print(
            f"[{tag}] (perplexity) {c['claim_id']:28s} domain={c['domain']:14s} tier={c['tier']} "
            f"predicted={predicted:13s} truth={c['ground_truth_verdict']:13s} "
            f"severity={severity:17s} fab={fabricated!s:5s} latency={latency:.2f}s cost=${cost:.6f}"
        )

    if bugs_found:
        chunk_lines = [f"\n## Test #3 Perplexity batch `{tag}` — {len(bugs_found)} dangerous/crash result(s) "
                        f"(external API baseline; not a pipeline bug)\n\n"]
        for b in bugs_found:
            chunk_lines.append(f"### {b['claim_id']} ({b['domain']}, tier {b['tier']})\n")
            chunk_lines.append(f"- Claim: `{json.dumps(b['claim_payload'])}`\n")
            chunk_lines.append(f"- Perplexity predicted: **{b['predicted_verdict']}**, "
                                f"ground truth: **{b['ground_truth_verdict']}** ({b['severity']})\n")
            if b["error"]:
                chunk_lines.append(f"- Error: `{b['error']}`\n")
            chunk_lines.append("\n")
        locked_append(bugs_path, "".join(chunk_lines))

    print(f"\n=== {tag} (perplexity) total cost: ${total_cost:.6f} ===")
    return results
