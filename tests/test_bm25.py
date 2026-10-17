from anticassiopeia.retrieval.bm25 import BM25Index, tokenize
from anticassiopeia.retrieval.chunking import chunk_document


def test_tokenize_lowercases_and_keeps_part_numbers_and_units_intact():
    toks = tokenize("Bar30 is 0.245ns at MS5837-30BA, 500m depth.")
    assert "bar30" in toks
    assert "0.245ns" in toks  # unit stays attached to the number — by design, see _TOKEN_RE
    assert "ms5837-30ba" in toks
    assert "500m" in toks


def test_empty_corpus_search_returns_nothing():
    idx = BM25Index([])
    assert idx.search("anything") == []


def test_empty_query_returns_nothing():
    chunks = chunk_document("doc", "some real content about pressure sensors")
    idx = BM25Index(chunks)
    assert idx.search("   ") == []


def test_relevant_chunk_ranks_above_irrelevant_chunk():
    text = (
        "Maximum Rated Depth (Aluminum): 300 m\n"
        "Max forward speed: 1.5 m/s\n"
        "Buoyancy foam rated to 300 m\n"
    )
    chunks = chunk_document("doc", text, chunk_size=40, overlap=5)
    idx = BM25Index(chunks)
    hits = idx.search("aluminum maximum rated depth", top_k=5)
    assert hits, "expected at least one hit"
    assert "aluminum" in hits[0].chunk.text.lower()


def test_term_absent_from_corpus_does_not_crash_and_contributes_nothing():
    chunks = chunk_document("doc", "this corpus has no mention of the queried thing at all")
    idx = BM25Index(chunks)
    hits = idx.search("nonexistentquerytermxyz", top_k=5)
    assert hits == []


def test_scores_are_positive_and_sorted_descending():
    text = "pressure pressure pressure sensor.\nunrelated line about something else entirely.\n"
    chunks = chunk_document("doc", text, chunk_size=40, overlap=5)
    idx = BM25Index(chunks)
    hits = idx.search("pressure sensor", top_k=5)
    assert hits
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)
    assert all(s > 0 for s in scores)
