"""
Item 20 (external review, deferred compound-claim feature, sized by the
task itself at "2-3x everything else combined"): splits a compound claim
("A is true and B is true") into independent parts, verifies each through
the EXISTING engine/adapters unchanged, then rolls the sub-verdicts up
into one overall answer.

Honest scope, built in a single 2-hour-budgeted round (per instruction:
not a production-ready feature, don't expect everything built,
partial-but-reachable is worse than honestly-incomplete-and-documented):

- DECOMPOSITION (the LLM pass) only ever classifies a sub-claim into
  "substrate" or "searchlight" -- the two domains that accept a bare,
  free-text claim with `context={}` and do their own retrieval. It
  NEVER invents an `quant`/`silicon` sub-claim, because those
  domains need a real `dataset_path`/`report_path` and structured
  numeric context (column, stat, metric, comparator, expected_value)
  that nothing about a free-text sentence can honestly supply -- an LLM
  "filling in" a plausible-looking file path or expected value would be
  exactly the kind of fabrication this whole project exists to prevent.
  A sub-claim the model itself flags as needing one of those two domains
  is kept as a named, visible gap, not silently dropped or guessed at.
- ROLLUP is AND-semantics only ("A and B" is the only connective this
  implements): ANY sub-verdict CONTRADICTED makes the whole thing
  CONTRADICTED (one false part falsifies an AND); ALL sub-verdicts
  CONFIRMED makes it CONFIRMED; anything else (an UNDETERMINED part, or
  no sub-claims survived decomposition at all) is UNDETERMINED. No
  OR/NOT connectives, no partial-credit scoring.
- WIRED to an HTTP endpoint as of v3 §1.2 (`POST /verify/compound` in
  `api/server.py`) — stale note from this module's original 2-hour-
  budgeted round, corrected here rather than left to mislead a future
  reader. The endpoint does NOT call `verify_compound()` below as one
  atomic call, though — it calls `decompose_claim()` directly, checks a
  hard cap on decomposed sub-claim count BEFORE verifying anything (this
  function has no such cap, and verifying every part before checking one
  would waste exactly the live calls a cap exists to bound), then runs
  the same per-part `engine.verify()` + `rollup()` loop inline. See
  `server.py`'s `verify_compound_endpoint()` docstring for why its own
  signature doesn't line up with reusing this function directly.
  `verify_compound()` itself remains real, tested, callable library code
  — exercised directly by `tests/test_compound.py`, just not the code
  path the live endpoint actually takes. Still NOT exposed through
  `default_domains()` (never has been, and still shouldn't be — this
  isn't a `DomainAdapter`). See docs/ARCHITECTURE.md's "Item 20" and
  "v3 §1.2" sections for the full history.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from anticassiopeia.core.domain import DomainAdapter
from anticassiopeia.core.engine import VerificationEngine
from anticassiopeia.core.verdict import Claim, Verdict, VerdictState

#: The only domains decomposition is allowed to produce a sub-claim for —
#: see module docstring for why quant/silicon are deliberately excluded.
DECOMPOSABLE_DOMAINS = frozenset({"substrate", "searchlight"})

_DECOMPOSE_SYSTEM_PROMPT = """You split ONE claim into its independent, individually \
checkable parts (e.g. "X and Y" becomes two parts: "X" and "Y"). If the claim is not \
actually compound — only one independent checkable part — return exactly one part, \
copying the claim text as-is.

Each part must be a complete, self-contained, checkable statement in plain English \
(it must make sense read on its own, with no "it"/"this" referring back to the other \
part), and must be classified into EXACTLY ONE of these domains:
- "substrate": a physical hardware/datasheet fact about named Blue Robotics hardware \
(e.g. BlueROV2, Bar30, Bar100XT) or similar physical equipment.
- "searchlight": a general factual claim checkable against public web sources \
(software, protocols, companies, people, standards, general technology facts).
- "unsupported": a claim that needs a SPECIFIC dataset file/statistic or a SPECIFIC \
FPGA timing/register report to check — do not guess a file path or a number; just \
classify it "unsupported" and leave "text" as the original wording.

Respond with ONLY this JSON shape, no other text, no markdown fences:
{"parts": [{"text": "...", "domain": "substrate"|"searchlight"|"unsupported"}, ...]}"""


@dataclass(frozen=True)
class SubClaimResult:
    text: str
    domain: str                 # one of DECOMPOSABLE_DOMAINS, or "unsupported"
    verdict: Verdict | None = None  # None exactly when domain == "unsupported" (never verified)


@dataclass(frozen=True)
class CompoundVerdict:
    claim_text: str
    state: VerdictState
    confidence: float | None
    sub_claims: list[SubClaimResult]
    reasoning: list[str] = field(default_factory=list)


class DecompositionError(Exception):
    """Raised when the LLM call itself fails or its response doesn't parse —
    never silently swallowed into a guessed decomposition."""


def _strip_code_fences(text: str) -> str:
    """Same convention as retrieval/extract.py's _parse_response — models
    sometimes wrap JSON in a fenced code block despite instructions."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return text


def _parse_decomposition(raw: str) -> list[dict]:
    """Separate from decompose_claim() so it's unit-testable against a canned
    string without a live LLM call — same reasoning as extract.py's
    _parse_response. Returns the raw list of {"text", "domain"} dicts;
    does not yet validate domain membership (the caller does that, since
    an unrecognized domain string is a DIFFERENT, more specific failure
    than a JSON-shape failure)."""
    text = _strip_code_fences(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DecompositionError(f"Model response was not valid JSON after stripping fences: {raw!r}") from exc

    parts = data.get("parts")
    if not isinstance(parts, list) or not parts:
        raise DecompositionError(f"Model response had no non-empty 'parts' list: {data!r}")

    for p in parts:
        if not isinstance(p, dict) or "text" not in p or "domain" not in p:
            raise DecompositionError(f"Each part must have 'text' and 'domain': {p!r}")
        if not isinstance(p["text"], str) or not p["text"].strip():
            raise DecompositionError(f"Part has an empty/non-string 'text': {p!r}")

    return parts


async def decompose_claim(client, claim_text: str) -> list[dict]:
    """Calls the LLM once to split `claim_text` into parts. `client` is
    duck-typed to NebiusTokenFactoryClient's `complete(prompt, *, system=None,
    temperature=0.0) -> str` interface — injectable with a fake for tests,
    same pattern retrieval/extract.py's propose() already uses.

    Raises DecompositionError on any failure (network, malformed JSON,
    missing fields) — the caller (verify_compound) turns that into an
    honest UNDETERMINED verdict, never a guessed split."""
    try:
        raw = await client.complete(claim_text, system=_DECOMPOSE_SYSTEM_PROMPT, temperature=0.0)
    except DecompositionError:
        raise
    except Exception as exc:  # noqa: BLE001 -- any client failure (network, auth, ...) is an honest gap, not a crash
        raise DecompositionError(f"LLM call failed: {type(exc).__name__}: {exc}") from exc
    return _parse_decomposition(raw)


def rollup(sub_results: list[SubClaimResult]) -> tuple[VerdictState, float | None, list[str]]:
    """Pure AND-rollup, no I/O — see module docstring for the semantics.
    Returns (overall_state, overall_confidence, reasoning_lines).

    Confidence choice (same "arbitrary but documented, not hidden"
    convention as engine.py's own thresholds): CONTRADICTED takes the
    HIGHEST confidence among the contradicting parts (only one needs to
    be false to falsify the whole AND, so the strongest evidence of
    falsity drives the overall number); CONFIRMED takes the LOWEST
    confidence among the confirming parts (the AND is only as certain as
    its least-certain part — a classic weakest-link choice, not fit to
    any data, same caveat DESIGN.md already states about the base engine's
    own thresholds)."""
    reasoning: list[str] = []
    verified = [r for r in sub_results if r.verdict is not None]
    unsupported = [r for r in sub_results if r.verdict is None]

    for r in unsupported:
        reasoning.append(f"Part {r.text!r} needs domain {r.domain!r}, which this decomposition cannot supply a structured context for — left as an open gap, not guessed.")

    if not verified:
        reasoning.append("No part of this compound claim could be independently verified.")
        return VerdictState.UNDETERMINED, None, reasoning

    contradicted = [r for r in verified if r.verdict.state == VerdictState.CONTRADICTED]
    undetermined = [r for r in verified if r.verdict.state == VerdictState.UNDETERMINED]
    confirmed = [r for r in verified if r.verdict.state == VerdictState.CONFIRMED]

    if contradicted:
        confidences = [r.verdict.confidence for r in contradicted if r.verdict.confidence is not None]
        reasoning.append(
            f"{len(contradicted)} of {len(verified)} verified part(s) are CONTRADICTED — "
            "falsifies the whole compound (AND) claim."
        )
        return VerdictState.CONTRADICTED, (max(confidences) if confidences else None), reasoning

    if undetermined or unsupported:
        reasoning.append(
            f"{len(undetermined)} verified part(s) are UNDETERMINED"
            + (f" and {len(unsupported)} part(s) are unsupported" if unsupported else "")
            + " — not enough to confirm the whole compound claim, and nothing contradicts it either."
        )
        return VerdictState.UNDETERMINED, None, reasoning

    confidences = [r.verdict.confidence for r in confirmed if r.verdict.confidence is not None]
    reasoning.append(f"All {len(confirmed)} verified part(s) are CONFIRMED — the whole compound (AND) claim holds.")
    return VerdictState.CONFIRMED, (min(confidences) if confidences else None), reasoning


async def verify_compound(
    engine: VerificationEngine, client, claim_text: str
) -> CompoundVerdict:
    """The full orchestration: decompose -> verify each part through the
    REAL engine (unchanged, same adapters, same scoring) -> roll up.

    A decomposition failure (DecompositionError, e.g. a dead LLM call) is
    an honest UNDETERMINED for the whole compound claim, with the real
    error named in reasoning — never a guessed split, never a crash."""
    try:
        parts = await decompose_claim(client, claim_text)
    except DecompositionError as exc:
        return CompoundVerdict(
            claim_text=claim_text, state=VerdictState.UNDETERMINED, confidence=None, sub_claims=[],
            reasoning=[f"Could not decompose this claim into parts: {exc}"],
        )

    sub_results: list[SubClaimResult] = []
    for part in parts:
        text, domain = part["text"], part["domain"]
        if domain not in DECOMPOSABLE_DOMAINS:
            sub_results.append(SubClaimResult(text=text, domain="unsupported", verdict=None))
            continue
        verdict = await engine.verify(Claim(text=text, domain=domain, context={}))
        sub_results.append(SubClaimResult(text=text, domain=domain, verdict=verdict))

    state, confidence, reasoning = rollup(sub_results)
    return CompoundVerdict(claim_text=claim_text, state=state, confidence=confidence, sub_claims=sub_results, reasoning=reasoning)
