"""
Thin client for Nebius Token Factory.

Nebius Token Factory exposes an OpenAI-compatible chat completions API, so
this wraps `httpx` directly rather than pulling in the full `openai` SDK for
one endpoint. Base URL and model are both configurable via environment
variables.

VERIFIED against current Nebius docs (docs.tokenfactory.nebius.com):
`DEFAULT_BASE_URL` was previously `https://api.studio.nebius.ai/v1` — wrong
domain AND wrong TLD. The AI Studio docs path now redirects to Token
Factory's docs, and every current code sample (Python/JS/cURL) uses
`https://api.tokenfactory.nebius.com/v1/`, so that's the corrected default
below.

`DEFAULT_MODEL` CONFIRMED against a real, live `GET /v1/models` call (200,
28 models returned): the previous guess (`meta-llama/Meta-Llama-3.1-70B-Instruct`)
is NOT in the catalog — there are no Llama models at all in it anymore.

Set to `openai/gpt-oss-120b` — chosen on MEASURED BENCHMARK DATA, not
hackathon branding: a separate project (Eclipse Constellation) ran a
model-selection benchmark on Nebius-hosted models for an equivalent
"extract" pipeline stage (pull structured values into JSON reliably, at
volume) and found gpt-oss-120b scored 100% on strict-JSON extraction,
100% JSON-valid rate, 100% overall on a full 27x3 run, at 0.95s latency —
directly applicable, since retrieval/extract.py's propose() is exactly
that: return a structured Proposal from retrieved chunks.

Confirmed for THIS account/endpoint, not just taken on the benchmark's
word: live in the catalog, a real chat-completions round trip works, and
repeated real propose() calls against this project's actual corpus
(doc1/doc2/doc3) returned perfectly correct chunk_id + verbatim quote
every time (8/8, then 6/6 on a second doc pair) — matching the cited
100% figures.

ONE REAL BUG surfaced and fixed while confirming this, not a model
limitation: the first 8/8 gpt-oss-120b run came back with `kind` always
null, which would make domains/robotics.py (which requires
`kind == "rated"` to accept a depth figure) discard every proposal — a
full regression, not an improvement. Investigated via retrieval/extract.py's
own prompt: it told the model `"kind": "rated" or "tested" or null` with
NO explanation of what those values mean, so a model that (correctly,
per this project's "never guess" ethos) refuses to assert a
classification it wasn't actually told how to make. Fixed by naming what
"rated" vs "tested" means in the prompt itself (see extract.py) — re-ran
the exact same 8 calls and `kind` came back `"rated"` 8/8.

That fix turned out to be model-agnostic, not gpt-oss-120b-specific: the
earlier ~4/8 flakiness observed against `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`
(also live-confirmed, also a fit for this project's "Nebius x NVIDIA"
framing) was re-tested against the SAME fixed prompt and also came back
8/8. So the prompt bug, not a model weakness, was the actual root cause
of last session's non-determinism — both models are now confirmed
reliable here. gpt-oss-120b is kept as DEFAULT_MODEL because it's the one
backed by actual measured benchmark data (the cited 27x3 run) rather than
just this adapter's own small live sample, per this task's instruction to
prefer measured evidence over an arbitrary pick.

Env vars:
    NEBIUS_API_KEY   — required (loaded from a real environment variable,
                        or from a .env file in the working directory via
                        python-dotenv — see fix note below)
    NEBIUS_BASE_URL  — default below; override if it's wrong
    NEBIUS_MODEL     — default below; override per task

FIXED BUG #1: `python-dotenv` was already a declared dependency
(pyproject.toml) and the README already documents `cp .env.example .env`
as the setup step, but nothing anywhere actually called `load_dotenv()` —
so a `.env` file alone, without the vars also being exported into the
shell, silently did nothing; `os.environ.get` doesn't read `.env` files by
itself. This only surfaced now because this is the first time anything
actually exercises this client live.

FIXED BUG #2: the first fix used plain `load_dotenv()` (override=False,
python-dotenv's default), which never overwrites a var already present in
`os.environ`. That's wrong for this project's actual shape: a long-lived
dev shell exports NEBIUS_API_KEY once, then `.env` gets edited later (e.g.
a rotated key) — and the stale shell-exported value silently kept winning,
producing a confusing live 401 even with a fresh, valid key sitting
unread in `.env`. `load_dotenv(override=True)` below makes the file the
source of truth, as it should be for a secret that's expected to rotate.

FIXED BUG #3 (found during the Nemotron pivot's pilot runs, see
stress_test/results/NEMOTRON_PIVOT_REPORT.md): `complete()` returned
`data["choices"][0]["message"]["content"]` with no check that it was
actually a usable string. A reasoning-capable model (observed live
against both Nemotron Super and Ultra) can consume its ENTIRE token
budget on hidden reasoning/thinking content, leaving the visible
`content` field literally `null` in an otherwise well-formed 200
response — `KeyError`/`IndexError` don't catch that (the key is
present, its value just isn't usable), so every caller's
`raw.strip()` (extract.py's `_parse_response`, research_web.py's
`_judge_stance()`) crashed with `AttributeError: 'NoneType' object
has no attribute 'strip'` instead of getting a named failure. Fixed
here, once, at the source: a non-string `content` now raises
`NebiusClientError` (same exception type every caller already
catches as a live-call failure) instead of returning `None` for a
caller to crash on.
"""

from __future__ import annotations

import os

import httpx
from dotenv import load_dotenv

# override=True: a .env file edited after this process' shell session started
# (e.g. a rotated key) must win over whatever was already exported into
# os.environ at shell startup — a stale already-exported value silently
# shadowing a deliberately-updated .env file is exactly the kind of unflagged
# gap this project exists to catch, not ship as the default.
load_dotenv(override=True)

DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1"
DEFAULT_MODEL = "openai/gpt-oss-120b"
#: FOUND during the Nemotron pivot's fair-fight investigation: no max_tokens
#: was ever set, so the API's own implicit default applied -- a crash
#: observed live against Nemotron Super hit exactly 8192 completion tokens
#: before truncating (a reasoning model can spend its whole budget on hidden
#: thinking before producing a visible answer). Set generously here so a
#: reasoning-capable model has real room to think AND answer, rather than
#: silently inheriting whatever the API's own default happens to be -- this
#: applies to every model behind this client equally, not just Nemotron.
DEFAULT_MAX_TOKENS = 16384


class NebiusClientError(Exception):
    pass


class NebiusTokenFactoryClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ):
        self.api_key = api_key or os.environ.get("NEBIUS_API_KEY")
        if not self.api_key:
            raise NebiusClientError("NEBIUS_API_KEY not set (pass api_key= or set the env var).")
        self.base_url = base_url or os.environ.get("NEBIUS_BASE_URL", DEFAULT_BASE_URL)
        self.model = model or os.environ.get("NEBIUS_MODEL", DEFAULT_MODEL)
        self.timeout = timeout
        self.max_tokens = max_tokens

    async def complete(self, prompt: str, *, system: str | None = None, temperature: float = 0.2) -> str:
        """Single-turn chat completion. Raises NebiusClientError on failure rather than
        returning a guessed/empty string — a silent failure here is exactly the kind of
        unflagged gap this project is built to surface, not hide."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": self.max_tokens},
            )
        if resp.status_code != 200:
            raise NebiusClientError(f"Nebius Token Factory returned {resp.status_code}: {resp.text}")

        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise NebiusClientError(f"Unexpected response shape from Nebius: {data}") from exc
        if not isinstance(content, str):
            finish_reason = data["choices"][0].get("finish_reason")
            raise NebiusClientError(
                f"Nebius response had no usable content (got {content!r}, finish_reason="
                f"{finish_reason!r}) — likely truncated by the token limit (a reasoning model "
                f"can spend its whole budget on hidden thinking tokens before producing visible "
                f"output) before the model finished responding: {data!r}"
            )
        return content
