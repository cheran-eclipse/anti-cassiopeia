"""
Tests for api/upload_store.py's UploadStore -- offline, no network, no
server. Same TTL/cap-eviction discipline as api/server.py's own rate-limit
buckets; same "monkeypatch a tiny cap/clock, prove the invariant directly"
style test_api_server.py already uses for that module's eviction test.
"""

import time

from anticassiopeia.api.upload_store import StoredDocument, UploadStore


def test_put_then_get_returns_the_same_document():
    store = UploadStore()
    doc = store.put(filename="a.txt", text="hello world", size_bytes=11, owner_key_hash="owner-a")
    fetched = store.get(doc.document_id)
    assert fetched == doc
    assert fetched.filename == "a.txt"
    assert fetched.text == "hello world"
    assert fetched.size_bytes == 11


def test_document_ids_are_opaque_and_distinct_across_puts():
    store = UploadStore()
    doc1 = store.put(filename="a.txt", text="x", size_bytes=1, owner_key_hash="owner-a")
    doc2 = store.put(filename="a.txt", text="x", size_bytes=1, owner_key_hash="owner-a")
    assert doc1.document_id != doc2.document_id
    # long enough (secrets.token_urlsafe(32)) that it isn't a guessable path,
    # unlike the raw filesystem paths quant.py/silicon.py have to
    # harden against in _path_safety.py (see this module's own docstring).
    assert len(doc1.document_id) > 32


def test_unknown_document_id_returns_none_not_a_crash():
    store = UploadStore()
    assert store.get("this-id-was-never-issued") is None


def test_expired_document_returns_none_and_is_actually_evicted():
    store = UploadStore(ttl_seconds=0.05)
    doc = store.put(filename="a.txt", text="x", size_bytes=1, owner_key_hash="owner-a")
    assert store.get(doc.document_id) is not None
    time.sleep(0.08)
    assert store.get(doc.document_id) is None
    # genuinely evicted from the dict, not just logically expired but still
    # held in memory -- same discipline as server.py's _make_room_for_one_more.
    assert doc.document_id not in store._documents


def test_fresh_document_does_not_expire_early():
    store = UploadStore(ttl_seconds=3600.0)
    doc = store.put(filename="a.txt", text="x", size_bytes=1, owner_key_hash="owner-a")
    assert store.get(doc.document_id) is not None


def test_cap_eviction_keeps_the_dict_bounded_even_transiently():
    """Proven directly against the real dict size, not just that the cap
    constant exists -- same standard test_api_server.py's own
    test_bucket_dict_is_evicted_when_it_grows_past_the_cap already holds
    itself to."""
    store = UploadStore(ttl_seconds=3600.0, max_documents=5)
    ids = [store.put(filename=f"{i}.txt", text="x", size_bytes=1, owner_key_hash="owner-a").document_id for i in range(5)]
    assert len(store._documents) == 5
    newest = store.put(filename="newest.txt", text="x", size_bytes=1, owner_key_hash="owner-a")
    assert len(store._documents) == 5  # never grew past the cap, even transiently
    assert newest.document_id in store._documents
    # the OLDEST entry (ids[0]) was the one evicted to make room
    assert ids[0] not in store._documents


def test_eviction_prefers_idle_expired_entries_before_cap_eviction():
    store = UploadStore(ttl_seconds=0.05, max_documents=3)
    old_ids = [store.put(filename=f"{i}.txt", text="x", size_bytes=1, owner_key_hash="owner-a").document_id for i in range(3)]
    time.sleep(0.08)  # all 3 are now expired by TTL, not just old
    fresh = store.put(filename="fresh.txt", text="x", size_bytes=1, owner_key_hash="owner-a")
    # expired entries were dropped by the TTL sweep, leaving room without
    # needing to fall through to pure age-based cap eviction
    assert len(store._documents) == 1
    assert fresh.document_id in store._documents
    for old_id in old_ids:
        assert old_id not in store._documents


def test_stored_document_is_frozen():
    doc = StoredDocument(document_id="x", filename="a.txt", text="hi", size_bytes=2, uploaded_at=0.0, owner_key_hash="owner-a")
    try:
        doc.filename = "b.txt"  # type: ignore[misc]
        assert False, "StoredDocument should be frozen/immutable"
    except AttributeError:
        pass


# --- v3 §2.1: ownership ---


def test_list_for_owner_never_returns_a_different_owners_documents():
    store = UploadStore()
    doc_a = store.put(filename="a.txt", text="mine", size_bytes=4, owner_key_hash="owner-a")
    store.put(filename="b.txt", text="not mine", size_bytes=8, owner_key_hash="owner-b")
    a_docs = store.list_for_owner("owner-a")
    assert [d.document_id for d in a_docs] == [doc_a.document_id]
    assert all(d.owner_key_hash == "owner-a" for d in a_docs)


def test_list_for_owner_with_no_uploads_returns_an_empty_list():
    store = UploadStore()
    store.put(filename="a.txt", text="x", size_bytes=1, owner_key_hash="owner-a")
    assert store.list_for_owner("owner-never-uploaded-anything") == []


def test_list_for_owner_is_most_recent_first():
    store = UploadStore()
    first = store.put(filename="first.txt", text="x", size_bytes=1, owner_key_hash="owner-a")
    second = store.put(filename="second.txt", text="x", size_bytes=1, owner_key_hash="owner-a")
    third = store.put(filename="third.txt", text="x", size_bytes=1, owner_key_hash="owner-a")
    ids = [d.document_id for d in store.list_for_owner("owner-a")]
    assert ids == [third.document_id, second.document_id, first.document_id]


def test_list_for_owner_excludes_expired_documents():
    store = UploadStore(ttl_seconds=0.05)
    store.put(filename="a.txt", text="x", size_bytes=1, owner_key_hash="owner-a")
    time.sleep(0.08)
    assert store.list_for_owner("owner-a") == []


def test_get_by_document_id_is_unaffected_by_ownership():
    """get() stays a pure id lookup -- any caller who has the opaque id can
    still resolve it, regardless of whose key uploaded it. Only
    list_for_owner() is ownership-scoped."""
    store = UploadStore()
    doc = store.put(filename="a.txt", text="x", size_bytes=1, owner_key_hash="owner-a")
    assert store.get(doc.document_id) == doc
