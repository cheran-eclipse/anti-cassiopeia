"""
Robotics domain adapter — physical/datasheet POV.

Verifies claims about real hardware against real, cited sources, now
routed through the real retrieve→verify pipeline in anticassiopeia.retrieval
instead of hand-typed Evidence objects: corpus text is chunked for real
(retrieval/chunking.py), BM25-searched for real (retrieval/bm25.py), and
every proposed quote is independently re-checked against the actual chunk
text for real (retrieval/verify.py) — nothing below gets to claim a
locator the verification step didn't actually confirm.

HONEST LIMITATION, stated plainly: the LLM "propose" step
(retrieval/extract.py) is NOT live here — there's no NEBIUS_API_KEY in
this build session. The Proposals below (`_KNOWN_PROPOSALS`) are authored
by this adapter directly, standing in for what `extract.propose()` would
return once that's wired to a real key. This is a real gap, not a design
choice: retrieve (BM25 search) and verify (verbatim re-check against the
actual chunk) are both fully real and run on every call; propose is
simulated. Swap `_lookup_proposal()` for a real `await propose(...)` call
once NEBIUS_API_KEY is available — the rest of the pipeline doesn't change.

Corpus: anticassiopeia/corpus/doc{1,2,3}_*.txt — partial excerpts
containing only the lines Constellation's own research directly quoted
and sourced (see docs/extracted/constellation-robotics-seed.md for full
provenance). The Bar30 excerpt deliberately omits Constellation's
canary-altered overpressure line entirely, not just avoids citing it.

Bar100XT and QuSpin QZFM Gen-3 still have no corpus — Constellation never
sourced them (narrative-only). Unchanged from before: an honest, specific
gap, not a guess.

Stance is derived per claim, not fixed at authoring time: the claim's depth
condition and polarity are read (see `_parse_condition`), the numeric spec is
re-parsed from the VERIFIED quote text (not trusted from the proposer's
`value`), converted to a depth rating in metres, and compared. So
"Bar30 survives 500 m" and "Bar30 fails at 500 m" get the same retrieved
evidence and OPPOSITE stances, as they must.

Claim contract (via Claim.context, preferred — no free-text parsing):
    {"depth_m": float, "polarity": "survives" | "fails"}   # polarity defaults to "survives"
If depth_m is absent, a deliberately narrow text grammar is tried
("<part> survives|withstands|fails|does not survive ... [at] <N> m [depth]").
Anything outside that grammar (negated verbs like "does not fail", other
units, no depth at all) is NOT guessed at: it returns no evidence and
describe_gap() names exactly what is missing.

Semantics, stated plainly: the sourced facts are RATINGS. "survives N m"
means N m is within the part's rated limit; "fails at N m" means N m exceeds
it. A rating is not a destructive test, so "fails" here means "beyond rated
spec", not "observed to break".

Pressure ratings (bar) are converted to depth with seawater density 1025
kg/m^3 and g = 9.80665 m/s^2, treating the figure as gauge pressure. The
gauge-vs-absolute ambiguity is ~3%, so a converted rating within 5% of the
claimed depth is recorded as neutral (no stance) instead of guessed at.
Ratings stated directly in metres are compared exactly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

from anticassiopeia.core.domain import DomainAdapter
from anticassiopeia.core.verdict import Claim, Evidence
from anticassiopeia.retrieval import BM25Index, Proposal, chunk_document, verify_proposal

_CORPUS_DIR = Path(__file__).parent.parent / "corpus"
_SEED_DOC = "docs/extracted/constellation-robotics-seed.md"

# doc_id -> (corpus file, trust). Stance is NOT stored here — it is derived per claim.
_SOURCES: dict[str, tuple[str, float]] = {
    "DOC1_BlueROV2": ("doc1_bluerov2_excerpt.txt", 0.8),
    "DOC2_BlueROV2": ("doc2_bluerov2_excerpt.txt", 0.7),
    "DOC3_Bar30": ("doc3_bar30_excerpt.txt", 0.85),
}

_SEAWATER_DENSITY = 1025.0  # kg/m^3
_GRAVITY = 9.80665          # m/s^2
_BAR_TO_PA = 1e5
#: A bar-derived depth within this fraction of the claimed depth is too close to call
#: given the gauge/absolute ambiguity — recorded as neutral, not guessed.
_CONVERSION_MARGIN = 0.05

_SPEC_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(m|bar)\b", re.IGNORECASE)

_POSITIVE_VERBS = r"survives?|withstands?"
_NEGATIVE_VERBS = r"fails?|does not survive|doesn't survive|cannot survive|can't survive|does not withstand|doesn't withstand"
_CLAIM_RE = re.compile(
    rf"^(?P<part>.+?)\s+(?:(?P<pos>{_POSITIVE_VERBS})|(?P<neg>{_NEGATIVE_VERBS}))"
    r"(?:\s+(?:at|to))?\s+(?P<depth>\d+(?:\.\d+)?)\s*m(?:eters?|etres?)?(?:\s+depth)?\s*[.!]?$",
    re.IGNORECASE,
)
# A negation inside the part-name span means the verb itself is negated ("does not fail").
_NEGATION_RE = re.compile(r"\b(?:not|never|cannot|can't|no)\b|n't\b", re.IGNORECASE)


@dataclass(frozen=True)
class _Condition:
    depth_m: float
    survives: bool  # True: claim asserts the part survives depth_m; False: asserts it fails there


def _parse_condition(claim: Claim) -> tuple[_Condition | None, str | None]:
    """Returns (condition, None) or (None, reason it could not be determined)."""
    ctx = claim.context
    if "depth_m" in ctx:
        try:
            depth = float(ctx["depth_m"])
        except (TypeError, ValueError):
            return None, f"context['depth_m'] is not a number: {ctx['depth_m']!r}."
        polarity = ctx.get("polarity", "survives")
        if polarity not in ("survives", "fails"):
            return None, f"context['polarity'] must be 'survives' or 'fails', got {polarity!r}."
        return _Condition(depth, polarity == "survives"), None

    m = _CLAIM_RE.match(claim.text.strip())
    if m is None or _NEGATION_RE.search(m.group("part")):
        return None, (
            "could not read an unambiguous depth condition from the claim text "
            "(supported: '<part> survives|withstands|fails [at] <N> m [depth]'); "
            "pass Claim.context={'depth_m': <metres>, 'polarity': 'survives'|'fails'} instead."
        )
    return _Condition(float(m.group("depth")), survives=m.group("pos") is not None), None


def _spec_depth_m(quote: str, proposal: Proposal) -> tuple[float | None, bool, str | None]:
    """Depth rating in metres from the VERIFIED quote text -> (depth_m, converted_from_bar, problem).

    The number comes from the quote itself, and must agree with what the
    proposer claimed — a mismatch is rejected, never reconciled in the proposer's favour.
    """
    specs = _SPEC_RE.findall(quote)
    if len(specs) != 1:
        return None, False, f"expected exactly one m/bar figure in the quote, found {len(specs)}"
    number, unit = float(specs[0][0]), specs[0][1].lower()
    if proposal.value is not None and (float(proposal.value) != number or (proposal.unit or "").lower() != unit):
        return None, False, (
            f"proposal says {proposal.value!r} {proposal.unit!r} but the quote states {number:g} {unit}"
        )
    if unit == "m":
        return number, False, None
    return number * _BAR_TO_PA / (_SEAWATER_DENSITY * _GRAVITY), True, None


def _derive_stance(spec_depth_m: float, converted: bool, cond: _Condition) -> str:
    if converted and abs(spec_depth_m - cond.depth_m) <= _CONVERSION_MARGIN * cond.depth_m:
        return "neutral"
    within_rating = spec_depth_m >= cond.depth_m
    return "supports" if within_rating == cond.survives else "contradicts"

# Stand-in for extract.propose() until NEBIUS_API_KEY is live — see module docstring.
# part keyword -> doc_id -> (retrieval_query, Proposal). retrieval_query is a real
# finding-question ("what's the housing depth rating"), NOT the raw claim text —
# a real datasheet doesn't restate the claim being checked, it states facts, and
# retrieval has to be searched for what the document would actually say. (Found
# this the hard way: Bar30's own chip datasheet excerpt never contains the string
# "Bar30" at all — it's framed entirely around pressure specs — so a BM25 search
# on the literal claim text "Bar30 survives 500m depth" matched nothing. Fixed by
# asking what the document would say, not what the claim says.)
# verify_proposal() independently re-checks every quote below against the real
# chunk text on every call — a wrong quote here fails loudly, not silently.
_KNOWN_PROPOSALS: dict[str, dict[str, tuple[str, Proposal]]] = {
    "bluerov2": {
        "DOC1_BlueROV2": (
            "maximum rated depth aluminum acrylic housing",
            Proposal(chunk_id="", quote="Maximum Rated Depth (Aluminum): 300 m", value=300, unit="m", kind="rated"),
        ),
        "DOC2_BlueROV2": (
            "maximum rated depth housing",
            Proposal(chunk_id="", quote="Maximum Rated Depth: 100 m", value=100, unit="m", kind="rated"),
        ),
    },
    "bar30": {
        "DOC3_Bar30": (
            "operating pressure range bar",
            Proposal(
                chunk_id="", quote="Operating range: 0 to 30 bar, -20 to +85 C", value=30, unit="bar", kind="rated"
            ),
        ),
    },
}


class RoboticsAdapter(DomainAdapter):
    domain_name = "robotics"
    implemented = True

    def __init__(self) -> None:
        # One BM25 index per corpus doc, built once at adapter construction —
        # real chunking + real indexing, not mocked.
        self._indexes: dict[str, BM25Index] = {}
        self._chunks_by_id: dict[str, dict] = {}
        for doc_id, (filename, _trust) in _SOURCES.items():
            path = _CORPUS_DIR / filename
            text = path.read_text()
            chunks = chunk_document(doc_id, text, chunk_size=300, overlap=50)
            self._indexes[doc_id] = BM25Index(chunks)
            self._chunks_by_id[doc_id] = {c.chunk_id: c for c in chunks}

    async def gather_evidence(self, claim: Claim) -> list[Evidence]:
        text = claim.text.lower()
        part = None
        if "bluerov2" in text or "blue rov" in text or "blue rov2" in text:
            part = "bluerov2"
        elif "bar30" in text or "bar 30" in text:
            part = "bar30"
        # Bar100XT / QuSpin: no corpus, no proposals — falls through to [] below,
        # same as before; describe_gap() names the reason specifically.

        if part is None:
            return []

        condition, _problem = _parse_condition(claim)
        if condition is None:
            return []  # describe_gap() names why — no depth comparison is guessed

        evidence: list[Evidence] = []
        for doc_id, (retrieval_query, proposal_template) in _KNOWN_PROPOSALS[part].items():
            _filename, trust = _SOURCES[doc_id]
            index = self._indexes[doc_id]

            # REAL retrieval step: BM25 search using a real finding-question, not
            # a hardcoded chunk_id — see _KNOWN_PROPOSALS' comment for why this is
            # a question about the document, not the claim text. If the real top
            # hit doesn't contain the known-correct quote, verify_proposal() below
            # will reject it, which is the honest outcome, not something to paper over.
            hits = index.search(retrieval_query, top_k=3)
            if not hits:
                continue  # no chunk even matched the query — no evidence from this doc

            # The numeric spec is read from the quote text and must match the proposer's
            # value; stance follows from comparing it with THIS claim's condition.
            spec_depth, converted, _problem = _spec_depth_m(proposal_template.quote, proposal_template)
            if spec_depth is None or proposal_template.kind != "rated":
                continue  # not a usable rated depth figure — no evidence from this doc
            stance = _derive_stance(spec_depth, converted, condition)

            # Try the proposal's quote against each retrieved candidate chunk, in
            # ranked order, rather than assuming the #1 hit is always right.
            accepted = None
            for hit in hits:
                candidate = Proposal(
                    chunk_id=hit.chunk.chunk_id,
                    quote=proposal_template.quote,
                    value=proposal_template.value,
                    unit=proposal_template.unit,
                    kind=proposal_template.kind,
                )
                result = verify_proposal(
                    candidate, self._chunks_by_id[doc_id], source=doc_id, stance=stance, trust=trust
                )
                if result.accepted:
                    accepted = result
                    break
            if accepted and accepted.evidence:
                ev = accepted.evidence
                note = (
                    f" [rating ~{spec_depth:.0f} m depth-equivalent vs claimed {condition.depth_m:g} m: "
                    f"{'survives' if condition.survives else 'fails'} claim -> {stance}]"
                )
                evidence.append(replace(ev, snippet=ev.snippet + note))

        return evidence

    @staticmethod
    def _is_known_part(text: str) -> bool:
        return any(k in text for k in ("bluerov2", "blue rov", "bar30", "bar 30"))

    def describe_gap(self, claim: Claim, evidence: list[Evidence]) -> list[str]:
        if evidence:
            return super().describe_gap(claim, evidence)

        text = claim.text.lower()
        if self._is_known_part(text):
            _cond, reason = _parse_condition(claim)
            if reason is not None:
                return [f"Part is in the corpus but the depth condition is unusable: {reason}"]
        if "bar100" in text or "bar 100" in text:
            return [
                "Bar100XT is a known revision-target part with NO sourced datasheet evidence "
                f"anywhere in Constellation — only a planning narrative ({_SEED_DOC} §3). "
                "A real Blue Robotics datasheet needs to be pulled before this can resolve "
                "past UNDETERMINED."
            ]
        if "quspin" in text or "qzfm" in text:
            return [
                "QuSpin QZFM Gen-3 is a known candidate sensor with NO sourced datasheet evidence "
                f"anywhere in Constellation — only a planning narrative ({_SEED_DOC} §4). "
                "A real QuSpin datasheet needs to be pulled before this can resolve past "
                "UNDETERMINED."
            ]
        return [
            f"No datasheet or spec-sheet evidence found for this part/assembly claim in "
            f"this adapter's seeded corpus ({_CORPUS_DIR}). Robotics verdicts require a "
            "traceable datasheet locator, not a generated spec."
        ]
