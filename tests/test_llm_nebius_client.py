"""
Tests NebiusTokenFactoryClient.complete()'s response-shape handling —
specifically the FOUND BUG (Nemotron pivot pilot runs, see
stress_test/results/NEMOTRON_PIVOT_REPORT.md): a reasoning-capable model
can return `content: null` in an otherwise well-formed 200 response (its
whole token budget spent on hidden reasoning), and the old code returned
that `None` straight to the caller, which then crashed on `.strip()`
instead of getting a named, catchable failure.
"""

import httpx
import pytest

from anticassiopeia.llm.nebius_client import NebiusClientError, NebiusTokenFactoryClient


class _DummyAsyncClient:
    def __init__(self, response: httpx.Response):
        self._response = response
        self.last_post_kwargs: dict | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url: str, **kwargs) -> httpx.Response:
        self.last_post_kwargs = kwargs
        return self._response

    async def aclose(self) -> None:
        return None


def _response(json_body: dict, status_code: int = 200) -> httpx.Response:
    request = httpx.Request("POST", "https://api.tokenfactory.nebius.com/v1/chat/completions")
    return httpx.Response(status_code, request=request, json=json_body)


async def test_normal_string_content_is_returned_unchanged(monkeypatch):
    response = _response({"choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}]})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _DummyAsyncClient(response))

    client = NebiusTokenFactoryClient(api_key="k")
    result = await client.complete("prompt")

    assert result == "hello"


async def test_null_content_from_a_truncated_reasoning_response_is_a_named_error_not_a_crash(monkeypatch):
    """The exact shape observed live against Nemotron Super/Ultra: a 200
    response, `content: null`, `finish_reason` showing the real cause."""
    response = _response({"choices": [{"message": {"content": None}, "finish_reason": "length"}]})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _DummyAsyncClient(response))

    client = NebiusTokenFactoryClient(api_key="k")
    with pytest.raises(NebiusClientError) as exc_info:
        await client.complete("prompt")

    assert "no usable content" in str(exc_info.value)
    assert "length" in str(exc_info.value)  # names the real finish_reason, not just "something went wrong"


async def test_missing_content_key_entirely_is_also_a_named_error(monkeypatch):
    response = _response({"choices": [{"message": {}, "finish_reason": "stop"}]})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _DummyAsyncClient(response))

    client = NebiusTokenFactoryClient(api_key="k")
    with pytest.raises(NebiusClientError):
        await client.complete("prompt")


async def test_empty_choices_list_is_a_named_error_not_an_indexerror(monkeypatch):
    response = _response({"choices": []})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _DummyAsyncClient(response))

    client = NebiusTokenFactoryClient(api_key="k")
    with pytest.raises(NebiusClientError) as exc_info:
        await client.complete("prompt")

    assert "Unexpected response shape" in str(exc_info.value)


async def test_non_200_status_is_a_named_error(monkeypatch):
    response = _response({"detail": "unauthorized"}, status_code=401)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _DummyAsyncClient(response))

    client = NebiusTokenFactoryClient(api_key="k")
    with pytest.raises(NebiusClientError) as exc_info:
        await client.complete("prompt")

    assert "401" in str(exc_info.value)


async def test_max_tokens_is_actually_sent_in_the_request(monkeypatch):
    """FOUND BUG (Nemotron pivot's fair-fight investigation): no max_tokens was
    ever set, so the API's own implicit default applied -- a crash observed
    live hit exactly 8192 completion tokens before truncating. Fixed by
    setting it explicitly; this locks in that it's actually sent, not just
    documented as a constant nothing reads."""
    response = _response({"choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}]})
    dummy = _DummyAsyncClient(response)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: dummy)

    client = NebiusTokenFactoryClient(api_key="k", max_tokens=12345)
    await client.complete("prompt")

    assert dummy.last_post_kwargs["json"]["max_tokens"] == 12345


# --- embed() -- hybrid-retrieval build ---


def _embeddings_response(rows: list[dict], status_code: int = 200) -> httpx.Response:
    request = httpx.Request("POST", "https://api.tokenfactory.nebius.com/v1/embeddings")
    return httpx.Response(status_code, request=request, json={"data": rows})


async def test_embed_returns_vectors_in_request_order_not_response_order(monkeypatch):
    """The response is deliberately shuffled here -- embed() must re-sort by
    the response's own `index` field, never trust response row order."""
    response = _embeddings_response([
        {"embedding": [0.2, 0.2], "index": 1},
        {"embedding": [0.1, 0.1], "index": 0},
    ])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _DummyAsyncClient(response))

    client = NebiusTokenFactoryClient(api_key="k")
    vectors = await client.embed(["first text", "second text"])

    assert vectors == [[0.1, 0.1], [0.2, 0.2]]


async def test_embed_empty_input_returns_empty_list_without_a_network_call(monkeypatch):
    def _fail(**_):
        raise AssertionError("should never construct an AsyncClient for empty input")
    monkeypatch.setattr(httpx, "AsyncClient", _fail)

    client = NebiusTokenFactoryClient(api_key="k")
    assert await client.embed([]) == []


async def test_embed_sends_the_embedding_model_not_the_chat_model(monkeypatch):
    response = _embeddings_response([{"embedding": [0.1], "index": 0}])
    dummy = _DummyAsyncClient(response)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: dummy)

    client = NebiusTokenFactoryClient(api_key="k", model="some/chat-model", embedding_model="some/embed-model")
    await client.embed(["x"])

    assert dummy.last_post_kwargs["json"]["model"] == "some/embed-model"
    assert dummy.last_post_kwargs["json"]["model"] != "some/chat-model"


async def test_embed_row_count_mismatch_is_a_named_error_not_a_crash(monkeypatch):
    response = _embeddings_response([{"embedding": [0.1], "index": 0}])  # only 1 row for 2 inputs
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _DummyAsyncClient(response))

    client = NebiusTokenFactoryClient(api_key="k")
    with pytest.raises(NebiusClientError, match="1.*2|row"):
        await client.embed(["a", "b"])


async def test_embed_inconsistent_dimensions_is_a_named_error(monkeypatch):
    response = _embeddings_response([
        {"embedding": [0.1, 0.2], "index": 0},
        {"embedding": [0.1], "index": 1},
    ])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _DummyAsyncClient(response))

    client = NebiusTokenFactoryClient(api_key="k")
    with pytest.raises(NebiusClientError, match="inconsistent dimensions"):
        await client.embed(["a", "b"])


async def test_embed_non_200_status_is_a_named_error(monkeypatch):
    response = _embeddings_response([], status_code=401)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _DummyAsyncClient(response))

    client = NebiusTokenFactoryClient(api_key="k")
    with pytest.raises(NebiusClientError, match="401"):
        await client.embed(["a"])
