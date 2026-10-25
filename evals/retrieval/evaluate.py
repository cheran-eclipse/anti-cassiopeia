"""
Retrieval evaluation harness: BM25 vs vector vs hybrid, on a REAL,
hand-labelled question set against Anti-Cassiopeia's OWN real corpus and
BYOE fixture documents (substrate' seeded datasheets + the ODrive/NASA JPL
BYOE fixtures used in the v2 stress test) -- NOT Constellation's
synthetic datasheets. Same Recall@k / Hit@k / MRR metric shape as
Constellation's own retrieval/evaluate.py (reimplemented here against
this project's own chunk_document()/HybridIndex types, not copied code).

HONEST SCOPE: 13 questions across 6 real documents is a real, hand-
checked sample -- not a statistically powered benchmark. Every gold
quote is independently verified to actually appear (whitespace-
normalized) in its named file at load time, so re-chunking or a typo in
a question can't silently produce a false "pass" by matching nothing.
Roughly half the questions ("paraphrase" kind) are deliberately phrased
in different words than their gold passage, specifically to test
whether vector search can bridge a gap BM25 structurally cannot; the
other half ("keyword-overlap") use wording close to the source, so BM25
alone should already do fine on those -- this split is what makes the
per-kind breakdown below meaningful, not just the aggregate number.

Usage:
    PYTHONPATH=. python3 evals/retrieval/evaluate.py
        # REAL embeddings via Nebius (Qwen/Qwen3-Embedding-8B) -- a real,
        # small, measured cost; this is the only mode this script has,
        # unlike Constellation's own evaluate.py, which also offers a
        # free fake-stand-in embedder. See the hybrid-retrieval build's
        # own report for why a stand-in number is NOT published here as
        # if it validated anything (Constellation's own stand-in run
        # found BM25 beating hybrid under the fake embedder -- noise, not
        # signal -- see claude/ANTI_CASSIOPEIA_HYBRID_RETRIEVAL_BUILD_PROMPT.md §0).
"""

from __future__ import annotations

import json
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from anticassiopeia.llm.nebius_client import NebiusTokenFactoryClient  # noqa: E402
from anticassiopeia.retrieval import HybridIndex, chunk_document  # noqa: E402

KS = (1, 3, 5)
_WS_RE = re.compile(r"\s+")

QA_PATH = Path(__file__).parent / "questions.json"
#: Real documents this eval draws from -- the substrate seeded corpus
#: (short, real, provenance-documented excerpts) plus the two real BYOE
#: fixtures used in the v2 stress test. Deliberately NOT Constellation's
#: own synthetic datasheets (per the build spec's own §0 instruction).
_DOC_DIRS = [REPO_ROOT / "anticassiopeia/corpus", REPO_ROOT / "evals/fixtures"]


def _normalize(text: str) -> str:
    return _WS_RE.sub(" ", text).strip().lower()


def find_quote(quote: str, text: str) -> bool:
    return _normalize(quote) in _normalize(text)


def _find_doc(name: str) -> Path:
    for d in _DOC_DIRS:
        p = d / name
        if p.exists():
            return p
    raise FileNotFoundError(f"{name} not found in any of {_DOC_DIRS}")


@dataclass(frozen=True)
class Question:
    id: str
    question: str
    kind: str
    gold: frozenset[str]


@dataclass(frozen=True)
class Metrics:
    n: int
    recall: dict[int, float]
    hit: dict[int, float]
    mrr: float


def load_corpus(qa_path: Path = QA_PATH, *, chunk_size: int = 180, overlap: int = 30):
    spec = json.loads(qa_path.read_text())["questions"]
    all_chunks = []
    per_file: dict[str, list] = {}
    for name in sorted({q["file"] for q in spec}):
        text = _find_doc(name).read_text()
        chunks = chunk_document(name, text, chunk_size=chunk_size, overlap=overlap)
        per_file[name] = chunks
        all_chunks.extend(chunks)

    questions = []
    for q in spec:
        gold = frozenset(c.chunk_id for c in per_file[q["file"]] if find_quote(q["gold_quote"], c.text))
        if not gold:
            raise ValueError(
                f"{q['id']}: gold quote {q['gold_quote']!r} not found (whitespace-normalized) in "
                f"{q['file']} after chunking -- the question set itself is broken, fix before trusting any score."
            )
        questions.append(Question(q["id"], q["question"], q.get("kind", "plain"), gold))
    return all_chunks, questions


def score(questions: list[Question], ranked_by_question: dict[str, list[str]]) -> Metrics:
    recall: dict[int, list[float]] = defaultdict(list)
    hit: dict[int, list[float]] = defaultdict(list)
    rr: list[float] = []
    for q in questions:
        ranked = ranked_by_question[q.id]
        first = next((r for r, cid in enumerate(ranked, start=1) if cid in q.gold), None)
        rr.append(1.0 / first if first else 0.0)
        for k in KS:
            found = q.gold & set(ranked[:k])
            recall[k].append(len(found) / len(q.gold))
            hit[k].append(1.0 if found else 0.0)
    n = len(questions)
    return Metrics(
        n=n,
        recall={k: sum(v) / n for k, v in recall.items()},
        hit={k: sum(v) / n for k, v in hit.items()},
        mrr=sum(rr) / n,
    )


async def run() -> dict[str, dict[str, Metrics]]:
    """Metrics per configuration (bm25/vector/hybrid), overall and per
    question kind. Also prints real, measured cost and latency (§5 of
    the build spec) -- NOT estimated."""
    chunks, questions = load_corpus()
    client = NebiusTokenFactoryClient()

    index = HybridIndex(chunks)
    embed_start = time.monotonic()
    await index.embed(client)
    embed_latency = time.monotonic() - embed_start
    if index.embed_error:
        raise RuntimeError(f"Corpus embedding failed -- cannot run a real eval: {index.embed_error}")

    configs = ("bm25", "vector", "hybrid")
    ranked: dict[str, dict[str, list[str]]] = {c: {} for c in configs}
    query_latencies: dict[str, list[float]] = {c: [] for c in configs}
    for q in questions:
        for mode in configs:
            start = time.monotonic()
            result = await index.search(q.question, top_k=max(KS), client=client, mode=mode)
            query_latencies[mode].append(time.monotonic() - start)
            ranked[mode][q.id] = [sc.chunk.chunk_id for sc in result.scored]

    kinds = sorted({q.kind for q in questions})
    out: dict[str, dict[str, Metrics]] = {}
    for name in configs:
        out[name] = {"ALL": score(questions, ranked[name])}
        for kind in kinds:
            subset = [q for q in questions if q.kind == kind]
            out[name][kind] = score(subset, ranked[name])

    print(f"\nReal corpus embedding: {len(chunks)} chunks, {embed_latency:.2f}s (ONE batch call).")
    for mode in configs:
        lat = query_latencies[mode]
        print(f"Per-query latency, mode={mode}: mean {sum(lat)/len(lat):.3f}s over {len(lat)} queries")
    return out


def to_markdown(results: dict[str, dict[str, Metrics]], title: str) -> str:
    lines = [f"### {title}", "", "| config | n | R@1 | R@3 | R@5 | MRR | hit@3 |", "|---|---|---|---|---|---|---|"]
    scopes = ["ALL", *[s for s in next(iter(results.values())) if s != "ALL"]]
    for scope in scopes:
        if scope != "ALL":
            lines += ["", f"**{scope}**", "", "| config | n | R@1 | R@3 | R@5 | MRR | hit@3 |", "|---|---|---|---|---|---|---|"]
        for name, per in results.items():
            m = per[scope]
            lines.append(
                f"| {name} | {m.n} | {m.recall[1]:.2f} | {m.recall[3]:.2f} | {m.recall[5]:.2f} | "
                f"{m.mrr:.3f} | {m.hit[3]:.2f} |"
            )
    return "\n".join(lines)


async def main() -> int:
    results = await run()
    print()
    print(to_markdown(results, "Embedder: Qwen/Qwen3-Embedding-8B (live, real Nebius call)"))
    return 0


if __name__ == "__main__":
    import asyncio
    raise SystemExit(asyncio.run(main()))
