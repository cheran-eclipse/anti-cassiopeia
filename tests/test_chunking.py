from anticassiopeia.retrieval.chunking import chunk_document


def test_empty_document_produces_no_chunks():
    assert chunk_document("doc", "") == []


def test_short_document_produces_one_chunk_covering_the_whole_text():
    text = "a short document"
    chunks = chunk_document("doc", text, chunk_size=800, overlap=150)
    assert len(chunks) == 1
    assert chunks[0].start == 0
    assert chunks[0].end == len(text)
    assert chunks[0].text == text


def test_every_chunk_offset_is_exact_and_reconstructs_the_source():
    text = "line one\nline two\nline three\nline four\nline five\n" * 5
    chunks = chunk_document("doc", text, chunk_size=40, overlap=10)
    assert len(chunks) > 1
    for c in chunks:
        # the single invariant this whole module exists to guarantee:
        # chunk.text must be EXACTLY text[start:end], always
        assert text[c.start : c.end] == c.text


def test_chunks_overlap_and_cover_the_whole_document():
    text = "x" * 500
    chunks = chunk_document("doc", text, chunk_size=100, overlap=20)
    assert chunks[0].start == 0
    assert chunks[-1].end == len(text)
    for prev, cur in zip(chunks, chunks[1:]):
        assert cur.start < prev.end  # real overlap, not a gap
        assert cur.start > prev.start  # always forward progress


def test_chunk_ids_are_unique_and_stable_per_doc():
    chunks = chunk_document("mydoc", "x" * 1000, chunk_size=100, overlap=20)
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))
    assert all(cid.startswith("mydoc#") for cid in ids)


def test_line_start_matches_actual_line_number():
    text = "line1\nline2\nline3\nline4\nline5\n" * 10
    chunks = chunk_document("doc", text, chunk_size=30, overlap=5)
    for c in chunks:
        # line_start must equal 1 + the number of newlines before c.start
        expected_line = text.count("\n", 0, c.start) + 1
        assert c.line_start == expected_line


def test_rejects_overlap_greater_than_or_equal_to_chunk_size():
    import pytest

    with pytest.raises(ValueError):
        chunk_document("doc", "some text", chunk_size=50, overlap=50)
