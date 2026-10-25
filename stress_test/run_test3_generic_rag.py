"""
Stress Test #3, variant 4: a self-built, generic, FacTool/RARR-style RAG
checker -- a competent, honest baseline for "what a typical off-the-shelf
fact-checker looks like", not a strawman. Deliberately NAIVE relative to
Anti-Cassiopeia's own adapters:

- No domain-specific adapters, no per-part routing, no exact computation
  for ml_data/fpga_embedded, no query-disambiguation logic.
- Retrieval is mechanical and generic: chunk the real source text/file
  (reusing retrieval/chunking.py and retrieval/bm25.py AS-IS, exactly
  like the task allows), then BM25-search with the RAW CLAIM TEXT as
  the query -- never a domain-tuned finding-question.
- One LLM completion over the retrieved context, asked a generic
  support/contradict/not-address question. No propose()/verify_proposal()
  structured extraction, no independent re-check, no stance-judging call.

Per-domain "real source text" this variant retrieves over:
- robotics: all 3 corpus docs POOLED into one combined index (no
  part-routing -- a generic RAG system doesn't know BlueROV2 claims only
  need DOC1/DOC2).
- research_web: reuses research_web.py's own `_search_candidate_urls`
  (a plain, generic, keyless web-search utility -- not domain-tuned
  logic) with the claim text as the query (which is what production
  ALREADY does for candidate discovery -- the domain-tuned phrasing
  only exists later, in the propose() call this variant skips).
- ml_data/fpga_embedded: the actual real CSV/report FILE, read directly
  and chunked as plain text (no parsing, no computation) -- a generic
  RAG system has no notion of "this is tabular data with a mean to
  compute", it just sees text.

This is new code, lives only in stress_test/, imports anticassiopeia/
read-only (chunk_document, BM25Index, and research_web's own search
utility), and never calls verify_proposal or propose() at all.
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

from anticassiopeia.domains.research_web import _looks_like_block_page, _search_candidate_urls, _strip_html  # noqa: E402
from anticassiopeia.retrieval import BM25Index, chunk_document  # noqa: E402
from instrumented_client import BUDGET_HARD_STOP_USD, BudgetExceededError, InstrumentedNebiusClient, UsageTracker  # noqa: E402
from run_test1 import classify, locked_append  # noqa: E402
from run_test2_bare import is_fabricated_detail, shows_access_awareness  # noqa: E402

RAW_RESULTS_PATH = REPO_ROOT / "stress_test/results/test3_generic_rag_raw.jsonl"
BUGS_PATH = REPO_ROOT / "stress_test/BUGS_FOUND.md"
_CORPUS_DIR = REPO_ROOT / "anticassiopeia/corpus"
_ROBOTICS_CORPUS_FILES = ["doc1_bluerov2_excerpt.txt", "doc2_bluerov2_excerpt.txt", "doc3_bar30_excerpt.txt"]

_TOP_K = 5
_MAX_CONTEXT_CHARS = 4000  # bounds the generic-RAG prompt's token cost; stated plainly in the report
_FETCH_TIMEOUT = 15.0

_CANONICAL_WORDS = ("confirmed", "contradicted", "undetermined")


#: FOUND BUG (external review, verified: 83 of 1,000 deduped main-sample
#: rows and 10 of 42 held-out rows): this prompt itself asks "does this
#: context support, contradict, or not address the claim" -- so the
#: model very consistently (83/83 of the affected rows, checked) answers
#: in ITS OWN echo of that wording ("**Supported** -- ...") rather than
#: the literal word "confirmed" the instructions separately asked for.
#: That's not the model failing to answer; it's this parser failing to
#: recognize an entirely predictable synonym its own prompt invited.
#: Mapped explicitly below, checked for "not/un-supported" BEFORE bare
#: "supported" so a genuine contradiction isn't mis-read as a confirmation.
_SYNONYM_MAP = (
    (re.compile(r"\b(not support(?:s|ed)?|unsupported|does(?:n't| not) support)\b"), "contradicted"),
    (re.compile(r"\bsupport(?:s|ed)?\b"), "confirmed"),
    (re.compile(r"\b(does(?:n't| not) address|unrelated|not addressed)\b"), "undetermined"),
)


def parse_rag_verdict(text: str) -> str:
    """Same parsing contract as run_test2_bare.parse_bare_verdict: first
    canonical word (or known synonym of one) by position, else a
    declined/unparseable fallback."""
    t = text.lower()
    positions = {}
    for word in _CANONICAL_WORDS:
        m = re.search(rf"\b{word}\b", t)
        if m:
            positions[word] = m.start()
    for pattern, canonical in _SYNONYM_MAP:
        m = pattern.search(t)
        if m and canonical not in positions:
            positions[canonical] = m.start()
        elif m and m.start() < positions[canonical]:
            positions[canonical] = m.start()
    if positions:
        return min(positions, key=positions.get)
    if shows_access_awareness(t) or "cannot determine" in t or "can't determine" in t:
        return "declined"
    return "unparseable"


_ROBOTICS_INDEX_CACHE: BM25Index | None = None


def _robotics_index() -> BM25Index:
    global _ROBOTICS_INDEX_CACHE
    if _ROBOTICS_INDEX_CACHE is None:
        chunks = []
        for filename in _ROBOTICS_CORPUS_FILES:
            text = (_CORPUS_DIR / filename).read_text()
            chunks.extend(chunk_document(filename, text, chunk_size=300, overlap=50))
        _ROBOTICS_INDEX_CACHE = BM25Index(chunks)
    return _ROBOTICS_INDEX_CACHE


async def _context_for_robotics(claim_text: str) -> tuple[str, str | None]:
    hits = _robotics_index().search(claim_text, top_k=_TOP_K)
    if not hits:
        return "", "no corpus chunk matched this claim's terms at all (BM25 found zero overlap)"
    return "\n---\n".join(h.chunk.text for h in hits), None


async def _context_for_research_web(claim_text: str) -> tuple[str, str | None]:
    urls = await _search_candidate_urls(claim_text, 5)
    if not urls:
        return "", "no live candidate page found via search for this claim"
    all_chunks = []
    notes = []
    for url in urls:
        try:
            async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT, follow_redirects=True) as client:
                resp = await client.get(url)
        except httpx.HTTPError as exc:
            notes.append(f"{url}: fetch failed ({exc!r})")
            continue
        if resp.status_code != 200 or _looks_like_block_page(resp.text):
            notes.append(f"{url}: unusable (HTTP {resp.status_code} or block page)")
            continue
        all_chunks.extend(chunk_document(url, _strip_html(resp.text)))
    if not all_chunks:
        return "", f"found {len(urls)} candidate URL(s) but none were fetchable: {'; '.join(notes)}"
    index = BM25Index(all_chunks)
    hits = index.search(claim_text, top_k=_TOP_K)
    if not hits:
        return "", "fetched candidate pages but none matched this claim's terms (BM25 found zero overlap)"
    return "\n---\n".join(h.chunk.text for h in hits), None


async def _context_for_file_domain(claim_payload: dict) -> tuple[str, str | None]:
    ctx = claim_payload.get("context", {})
    path_field = ctx.get("dataset_path") or ctx.get("report_path")
    if path_field is None:
        return "", "claim context has no dataset_path/report_path to read"
    paths = path_field if isinstance(path_field, list) else [path_field]

    all_chunks = []
    for p in paths:
        full_path = REPO_ROOT / p
        try:
            text = full_path.read_text()
        except OSError as exc:
            return "", f"could not read real source file {p}: {type(exc).__name__}: {exc}"
        all_chunks.extend(chunk_document(str(p), text, chunk_size=500, overlap=50))

    index = BM25Index(all_chunks)
    hits = index.search(claim_payload["text"], top_k=_TOP_K)
    if hits:
        chunk_texts = [h.chunk.text for h in hits]
    else:
        # Generic BM25 commonly fails to match a numeric claim's terms against a
        # header-plus-numbers file -- fall back to the first few chunks (what a
        # naive RAG system showing "the top of the file" would do) rather than
        # silently giving the model nothing.
        chunk_texts = [c.text for c in all_chunks[:_TOP_K]]
    return "\n---\n".join(chunk_texts), None


def _build_prompt(claim_text: str, context: str, gap_reason: str | None) -> str:
    if gap_reason is not None:
        context_block = f"(No retrieved context -- {gap_reason}.)"
    else:
        context_block = context[:_MAX_CONTEXT_CHARS]
    return (
        f"Context:\n{context_block}\n\n"
        f"Does this context support, contradict, or not address the following claim?\n"
        f"Claim: {claim_text}\n\n"
        f"Answer confirmed (if it supports the claim), contradicted (if it contradicts the claim), "
        f"or undetermined (if it doesn't address the claim), and explain briefly."
    )


async def run_generic_rag_batch(
    claims: list[dict],
    tag: str,
    *,
    raw_results_path: Path = RAW_RESULTS_PATH,
    bugs_path: Path = BUGS_PATH,
    tracker: UsageTracker | None = None,
    budget_usd: float = BUDGET_HARD_STOP_USD,
) -> list[dict]:
    tracker = tracker if tracker is not None else UsageTracker()
    client = InstrumentedNebiusClient(tracker, budget_usd=budget_usd)
    raw_results_path.parent.mkdir(parents=True, exist_ok=True)

    bugs_found: list[dict] = []
    results = []
    try:
        for c in claims:
            tracker.set_domain(c["domain"])
            before = tracker.snapshot()

            start = time.monotonic()
            error = None
            response_text = ""
            gap_reason = None
            try:
                if c["domain"] == "robotics":
                    context, gap_reason = await _context_for_robotics(c["claim_payload"]["text"])
                elif c["domain"] == "research_web":
                    context, gap_reason = await _context_for_research_web(c["claim_payload"]["text"])
                else:
                    context, gap_reason = await _context_for_file_domain(c["claim_payload"])

                prompt = _build_prompt(c["claim_payload"]["text"], context, gap_reason)
                response_text = await client.complete(prompt, temperature=0.2)
                predicted = parse_rag_verdict(response_text)
            except BudgetExceededError:
                raise
            except Exception as exc:  # noqa: BLE001
                predicted = "CRASH"
                error = f"{type(exc).__name__}: {exc}"
            latency = time.monotonic() - start

            after = tracker.snapshot()
            delta_cost = after["total_cost_usd"] - before["total_cost_usd"]

            classify_input = "undetermined" if predicted == "declined" else predicted
            severity = "crash" if predicted == "CRASH" else classify(classify_input, c["ground_truth_verdict"])
            fabricated = (
                False if predicted == "CRASH"
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
                "context_gap_reason": gap_reason,
                "latency_s": latency,
                "cost_usd": delta_cost,
                "response_text": response_text,
                "error": error,
            }
            results.append(record)
            locked_append(raw_results_path, json.dumps(record) + "\n")

            if severity in ("dangerous", "crash"):
                bugs_found.append({**record, "claim_payload": c["claim_payload"]})

            print(
                f"[{tag}] (generic-rag) {c['claim_id']:28s} domain={c['domain']:14s} tier={c['tier']} "
                f"predicted={predicted:13s} truth={c['ground_truth_verdict']:13s} "
                f"severity={severity:17s} fab={fabricated!s:5s} latency={latency:.2f}s cost=${delta_cost:.6f}"
            )
    except BudgetExceededError as exc:
        print(f"\nBUDGET HARD STOP (generic-rag): {exc}")

    if bugs_found:
        chunk_lines = [f"\n## Test #3 generic-RAG batch `{tag}` — {len(bugs_found)} dangerous/crash result(s) "
                        f"(a naive off-the-shelf-style baseline; not a pipeline bug)\n\n"]
        for b in bugs_found:
            chunk_lines.append(f"### {b['claim_id']} ({b['domain']}, tier {b['tier']})\n")
            chunk_lines.append(f"- Claim: `{json.dumps(b['claim_payload'])}`\n")
            chunk_lines.append(f"- Generic-RAG predicted: **{b['predicted_verdict']}**, "
                                f"ground truth: **{b['ground_truth_verdict']}** ({b['severity']})\n")
            if b["error"]:
                chunk_lines.append(f"- Error: `{b['error']}`\n")
            chunk_lines.append("\n")
        locked_append(bugs_path, "".join(chunk_lines))

    return results
