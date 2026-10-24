"""
Robotics domain adapter — physical/datasheet POV.

Verifies claims about real hardware against real, cited sources, now
routed through the real retrieve→verify pipeline in anticassiopeia.retrieval
instead of hand-typed Evidence objects: corpus text is chunked for real
(retrieval/chunking.py), BM25-searched for real (retrieval/bm25.py), and
every proposed quote is independently re-checked against the actual chunk
text for real (retrieval/verify.py) — nothing below gets to claim a
locator the verification step didn't actually confirm.

LLM "propose" step: LIVE, and the live round trip is CONFIRMED, not just
wired. `gather_evidence()` calls `retrieval.extract.propose()` for real
against `NebiusTokenFactoryClient`, feeding it the real BM25-retrieved
candidate chunks for a doc and taking back a real `Proposal` — not a
hand-authored stand-in. retrieve (BM25 search) and verify (verbatim
re-check against the actual chunk) were already real; propose is now
real too, so the full pipeline is real, start to finish, proven against
the genuine Nebius API (see `tests/test_domains_robotics.py`'s
`test_live_*` tests): a corpus fact gets real accepted evidence, and a
fact genuinely absent from the shown passages gets an honest "not found"
from the model, not a hallucination. `_RETRIEVAL_QUERIES` below only maps
part -> doc_id -> the finding-question handed to BM25 and then to the
model as context — it carries no answer.

RESOLVED (was a KNOWN LIMITATION): an early live run showed the `kind`
field ("rated" vs "tested" vs null) coming back inconsistent across
repeated identical calls — roughly half of an 8-call sample. Root cause
was NOT the model: `retrieval.extract.py`'s prompt told the model
`"kind": "rated" or "tested" or null` with no explanation of what those
values mean, so a model correctly (per this project's "never guess"
ethos) refused to assert a classification it was never actually told how
to make. Fixed by naming what "rated" vs "tested" means in the prompt
itself — re-verified live, repeatedly, at 8/8 and 6/6 across both models
tried (`openai/gpt-oss-120b`, the one kept; `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`,
also confirmed reliable after the same fix). `kind == "rated"` below is
still required exactly as before — it was never loosened to force a
number to look better; the prompt was the actual bug.

The client is injected (`RoboticsAdapter(client=...)`, defaulting to a
lazily-constructed `NebiusTokenFactoryClient()` on first real use) so
tests can supply a scripted fake client and exercise the real
propose()->verify_proposal() pipeline without a network call or a live
key. A `NebiusClientError` or network failure from the live client is
caught per-document and surfaced as a named gap via `describe_gap()` —
never a crash, and never silently treated as "no evidence" without
saying why — same pattern as domains/research_web.py's fetch-failure
handling.

Corpus: anticassiopeia/corpus/doc{1,2,3}_*.txt — partial excerpts
containing only the lines Constellation's own research directly quoted
and sourced (see docs/extracted/constellation-robotics-seed.md for full
provenance). The Bar30 excerpt deliberately omits Constellation's
canary-altered overpressure line entirely, not just avoids citing it.

Bar100XT: now sourced (this session) from Blue Robotics' real, live BarXT
product page — see doc4_bar100xt_excerpt.txt and
docs/extracted/constellation-robotics-seed.md §3 for the fetch. QuSpin
QZFM Gen-3 still has no numeric rating to source: QuSpin's own official
product page (fetched live this session, see §4) states no pressure/
depth/submersion rating anywhere at all, confirmed by reading the whole
page — a real, citable NEGATIVE finding now, not just an unsourced
narrative gap. Neither change invents a number; Bar100XT's figure is a
real manufacturer-stated rating, and QuSpin's "no rating stated" is a
real, checked absence.

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

import httpx

from anticassiopeia.core.domain import DomainAdapter
from anticassiopeia.core.verdict import Claim, Evidence
from anticassiopeia.llm.nebius_client import NebiusClientError, NebiusTokenFactoryClient
from anticassiopeia.retrieval import BM25Index, Proposal, ScoredChunk, chunk_document, verify_proposal
from anticassiopeia.retrieval.extract import propose

_CORPUS_DIR = Path(__file__).parent.parent / "corpus"
_SEED_DOC = "docs/extracted/constellation-robotics-seed.md"

# doc_id -> (corpus file, trust). Stance is NOT stored here — it is derived per claim.
_SOURCES: dict[str, tuple[str, float]] = {
    "DOC1_BlueROV2": ("doc1_bluerov2_excerpt.txt", 0.8),
    "DOC2_BlueROV2": ("doc2_bluerov2_excerpt.txt", 0.7),
    "DOC3_Bar30": ("doc3_bar30_excerpt.txt", 0.85),
    # Official manufacturer product page (no separate PDF datasheet exists for
    # this part — see doc4_bar100xt_excerpt.txt's header), same trust tier as
    # Bar30's chip datasheet: both are the manufacturer's own stated rating.
    "DOC4_Bar100XT": ("doc4_bar100xt_excerpt.txt", 0.85),
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


#: FOUND BUG this exists to fix (see stress_test/BUGS_FOUND.md): live
#: propose() calls against a real corpus doc were observed to return "not
#: found" roughly 1 in 10 times even though the fact is genuinely present
#: (confirmed: isolated repeats against the same doc/question succeeded
#: 10/10). A single empty result landing on just ONE side of a genuine
#: two-source conflict (e.g. BlueROV2's DOC1-vs-DOC2 disagreement in the
#: 100-300m range) meant the engine never saw the conflict and confidently
#: resolved off whichever one source survived -- the dangerous-direction
#: twin of the kind-field non-determinism already documented above (that
#: one always failed safely toward UNDETERMINED; this one didn't).
#: 3 independent attempts (not 1) drops a false "genuinely absent" call
#: from ~10% to roughly 10%^3 = ~0.1% -- a real, substantial improvement,
#: not cost added for its own sake: it only applies on the (uncommon)
#: retry path, not to every call, since most sources return evidence on
#: the first attempt and never retry at all.
_PROPOSE_RETRY_ATTEMPTS = 3


async def _propose_with_retry(
    question: str, hits: list[ScoredChunk], client: NebiusTokenFactoryClient, attempts: int = _PROPOSE_RETRY_ATTEMPTS
) -> Proposal | None:
    """Retries ONLY on genuine absence (propose() returning None) — never on
    an actual returned proposal, even a low-confidence-looking one, and
    never on a raised error (a live-call FAILURE is the already-handled
    propose_errors path in gather_evidence(), a different failure mode from
    the silent-absence one this function exists for; an exception here
    propagates immediately, it is not retried into a false "absent")."""
    proposal = None
    for _ in range(attempts):
        proposal = await propose(question, hits, client)
        if proposal is not None:
            return proposal
    return None  # genuinely absent across every attempt, not just one unlucky draw


# part keyword -> doc_id -> retrieval_query. retrieval_query is a real
# finding-question ("what's the housing depth rating"), NOT the raw claim text —
# a real datasheet doesn't restate the claim being checked, it states facts, and
# retrieval has to be searched for what the document would actually say. (Found
# this the hard way: Bar30's own chip datasheet excerpt never contains the string
# "Bar30" at all — it's framed entirely around pressure specs — so a BM25 search
# on the literal claim text "Bar30 survives 500m depth" matched nothing. Fixed by
# asking what the document would say, not what the claim says.) The same question
# is also what the model (extract.propose()) is asked, over the same candidate
# chunks BM25 retrieved — this dict carries no answer, only where to look.
#
# FOUND BUG, DOC1's query specifically (see stress_test/BUGS_FOUND.md's dated
# correction entry): the question used to read "maximum rated depth aluminum
# ACRYLIC housing", asking about BOTH materials at once even though DOC1's
# real corpus excerpt states TWO DIFFERENT real ratings for them ("Maximum
# Rated Depth (Acrylic): 100 m" and "...(Aluminum): 300 m" — both genuinely
# present in the same chunk). Confirmed live, repeatedly (20/20 before the
# fix landed on Acrylic in roughly 40% of calls — not rare, and not model
# unreliability: the model was answering an honestly ambiguous question
# correctly, just about whichever material it picked that time): that
# ambiguity, not absence, was the DOMINANT cause of the dangerous
# conflict-zone verdicts the stress test found. DOC1 is documented
# (docs/extracted/constellation-robotics-seed.md §1.1: "best-case figure...
# aluminum tube, 300 m, DOC1 only") as this project's own source for the
# ALUMINUM rating specifically — the query now says so, dropping "acrylic"
# entirely, and was re-verified 20/20 live after the fix (see
# tests/test_domains_robotics.py's dedicated resampling test).
_RETRIEVAL_QUERIES: dict[str, dict[str, str]] = {
    "bluerov2": {
        "DOC1_BlueROV2": "maximum rated depth aluminum housing",
        "DOC2_BlueROV2": "maximum rated depth housing",
    },
    "bar30": {
        "DOC3_Bar30": "operating pressure range bar",
    },
    # Deliberately NOT the same literal query string as "bar30"'s below, even
    # though both ask essentially the same question of a similarly-shaped
    # source — see tests/test_domains_robotics.py's _FakeClient, whose
    # substring-marker lookup can't disambiguate two docs sharing one exact
    # query string. Still shares enough real tokens ("operating"/"pressure"/
    # "bar") with doc4_bar100xt_excerpt.txt's actual text to BM25-match it.
    "bar100xt": {
        "DOC4_Bar100XT": "maximum operating pressure rating bar",
    },
}


class RoboticsAdapter(DomainAdapter):
    domain_name = "robotics"
    implemented = True

    def __init__(self, client: NebiusTokenFactoryClient | None = None) -> None:
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
        # Injected so tests can supply a scripted fake and default_domains() still
        # gets a real client — constructing NebiusTokenFactoryClient() only reads
        # env vars, it makes no network call, so doing this eagerly is safe even
        # when NEBIUS_API_KEY isn't set; the error surfaces per-call instead (see
        # gather_evidence below), as a named gap rather than a constructor crash.
        self._client = client
        self._client_error: str | None = None
        if self._client is None:
            try:
                self._client = NebiusTokenFactoryClient()
            except NebiusClientError as exc:
                self._client_error = str(exc)

    async def gather_evidence(self, claim: Claim) -> list[Evidence]:
        text = claim.text.lower()
        part = None
        if "bluerov2" in text or "blue rov" in text or "blue rov2" in text:
            part = "bluerov2"
        elif "bar100xt" in text or "bar 100xt" in text or "bar100" in text or "bar 100" in text:
            part = "bar100xt"
        elif "bar30" in text or "bar 30" in text:
            part = "bar30"
        # QuSpin: no numeric rating exists to source (confirmed live against
        # QuSpin's own official page — see describe_gap() below) — falls
        # through to [] below; describe_gap() names the reason specifically.

        if part is None:
            return []

        condition, _problem = _parse_condition(claim)
        if condition is None:
            return []  # describe_gap() names why — no depth comparison is guessed

        if self._client is None:
            # NEBIUS_API_KEY isn't configured at all — an honest, named gap,
            # not a crash. Distinct from a live call failing (handled below).
            return []

        evidence: list[Evidence] = []
        propose_errors: list[str] = []
        # FOUND BUG (external review): a source that returned something --
        # just an incomplete, ambiguous, or verification-rejected answer,
        # not a clean `None` -- used to `continue` with no trace at all.
        # Once any OTHER source alone produced enough evidence for a
        # confident verdict, that silently-dropped source vanished
        # completely; nothing in the final Verdict said it had even been
        # consulted. Every `continue` below that is NOT the genuine,
        # repeatedly-confirmed "fact absent" case now records WHY first,
        # via `partial_gaps`, surfaced unconditionally through
        # `describe_partial_gaps()` regardless of how confident the final
        # verdict ends up being (see core/domain.py's docstring for that
        # method and core/engine.py's unconditional call to it).
        partial_gaps: list[str] = []
        for doc_id, retrieval_query in _RETRIEVAL_QUERIES[part].items():
            _filename, trust = _SOURCES[doc_id]
            index = self._indexes[doc_id]

            # REAL retrieval step: BM25 search using a real finding-question, not
            # a hardcoded chunk_id or quote — see _RETRIEVAL_QUERIES' comment for
            # why this is a question about the document, not the claim text.
            hits = index.search(retrieval_query, top_k=3)
            if not hits:
                partial_gaps.append(
                    f"{doc_id}: expected as a source for '{part}' but BM25 found no chunk "
                    f"matching the retrieval query {retrieval_query!r} — the source may still "
                    "contain the relevant fact, phrased in a way this query didn't surface."
                )
                continue  # no chunk even matched the query — no evidence from this doc

            # REAL propose step: the model sees only these retrieved chunks and
            # either cites one verbatim or honestly reports it isn't there — never
            # trusted on its own, verify_proposal() below re-checks it regardless.
            # Retried on genuine absence only (see _propose_with_retry) — a single
            # "not found" is not trusted any more than a single quote's content is.
            try:
                proposal = await _propose_with_retry(retrieval_query, hits, self._client)
            except (NebiusClientError, httpx.HTTPError) as exc:
                propose_errors.append(f"{doc_id}: LLM propose call failed: {exc}")
                partial_gaps.append(f"{doc_id}: LLM propose call failed: {exc}")
                continue
            if proposal is None:
                # Genuinely absent, confirmed across every retry attempt — a real,
                # intentional outcome (see _propose_with_retry's docstring), but
                # still worth one line of record that this expected source was
                # checked and came back empty, not silently skipped.
                partial_gaps.append(
                    f"{doc_id}: checked, but the model reported no matching fact across "
                    f"{_PROPOSE_RETRY_ATTEMPTS} independent attempts — treated as genuinely absent."
                )
                continue  # model honestly, and REPEATEDLY, reported the fact isn't in these passages

            # The numeric spec is read from the quote text and must match the proposer's
            # value; stance follows from comparing it with THIS claim's condition.
            spec_depth, converted, problem = _spec_depth_m(proposal.quote, proposal)
            if spec_depth is None or proposal.kind != "rated":
                reason = problem or f"proposal.kind={proposal.kind!r}, expected 'rated'"
                partial_gaps.append(f"{doc_id}: got an answer, but it wasn't usable: {reason}.")
                continue  # not a usable rated depth figure — no evidence from this doc
            stance = _derive_stance(spec_depth, converted, condition)

            result = verify_proposal(proposal, self._chunks_by_id[doc_id], source=doc_id, stance=stance, trust=trust)
            if result.accepted and result.evidence:
                ev = result.evidence
                # Explicit about which claim shape this actually checks (external
                # review, "rated vs. survives" conflation): the adapter only ever
                # has RATED-limit data, never an observed destructive-test result,
                # regardless of whether the claim says "survives"/"fails" or "is
                # rated for" — stated here so the verdict itself says this, not
                # just a code comment a caller never sees.
                note = (
                    f" [checked against the manufacturer's RATED limit (not an observed "
                    f"destructive test): ~{spec_depth:.0f} m depth-equivalent rating vs "
                    f"claimed {condition.depth_m:g} m "
                    f"({'survives' if condition.survives else 'fails'} claim) -> {stance}]"
                )
                evidence.append(replace(ev, snippet=ev.snippet + note))
            elif not result.accepted:
                partial_gaps.append(f"{doc_id}: proposed quote failed independent verification against the source chunk.")

        self._last_propose_errors = propose_errors
        self._last_partial_gaps = partial_gaps
        return evidence

    def describe_partial_gaps(self, claim: Claim) -> list[str]:
        return list(getattr(self, "_last_partial_gaps", []))

    @staticmethod
    def _is_known_part(text: str) -> bool:
        return any(
            k in text
            for k in ("bluerov2", "blue rov", "bar100xt", "bar 100xt", "bar100", "bar 100", "bar30", "bar 30")
        )

    def describe_gap(self, claim: Claim, evidence: list[Evidence]) -> list[str]:
        if evidence:
            return super().describe_gap(claim, evidence)

        text = claim.text.lower()
        if self._is_known_part(text):
            _cond, reason = _parse_condition(claim)
            if reason is not None:
                return [f"Part is in the corpus but the depth condition is unusable: {reason}"]
            if self._client is None:
                return [
                    "Part is in the corpus and the depth condition parses fine, but the LLM "
                    f"propose step can't run: {self._client_error}"
                ]
            propose_errors = getattr(self, "_last_propose_errors", [])
            if propose_errors:
                return [
                    "Part is in the corpus and the depth condition parses fine, but the live "
                    "LLM propose call failed for every source doc: " + "; ".join(propose_errors)
                ]
        if "quspin" in text or "qzfm" in text:
            return [
                "QuSpin QZFM Gen-3 has NO pressure/depth/submersion rating anywhere on QuSpin's "
                "own official product page (confirmed live, 2026-10-24, "
                "https://quspin.com/qzfm-gen-3 — the whole page was read; it states sensitivity "
                "figures but never mentions pressure, depth, submersion, waterproofing, or an IP "
                f"rating) — see {_SEED_DOC} §4. This is a real, checked absence, not an unsourced "
                "gap, but it still means no numeric comparison is possible for ANY claimed depth: "
                "there is nothing to compare against, so this stays UNDETERMINED regardless of "
                "the depth asked about."
            ]
        return [
            f"No datasheet or spec-sheet evidence found for this part/assembly claim in "
            f"this adapter's seeded corpus ({_CORPUS_DIR}). Robotics verdicts require a "
            "traceable datasheet locator, not a generated spec."
        ]
