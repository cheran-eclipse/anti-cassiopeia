"""
Thin client for Nebius Token Factory.

Nebius AI Studio / Token Factory exposes an OpenAI-compatible chat
completions API, so this wraps `httpx` directly rather than pulling in the
full `openai` SDK for one endpoint. Base URL and model are both
configurable via environment variables — VERIFY the default base URL
against current Nebius docs before relying on it; it is written from
memory, not confirmed against a live call, and is exactly the kind of
unverified claim this project exists to catch.

Env vars:
    NEBIUS_API_KEY   — required
    NEBIUS_BASE_URL  — default below; override if it's wrong
    NEBIUS_MODEL     — default below; override per task
"""

from __future__ import annotations

import os

import httpx

DEFAULT_BASE_URL = "https://api.studio.nebius.ai/v1"  # TODO: confirm against current Nebius Token Factory docs
DEFAULT_MODEL = "meta-llama/Meta-Llama-3.1-70B-Instruct"  # TODO: pick the actual model(s) for this build


class NebiusClientError(Exception):
    pass


class NebiusTokenFactoryClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
    ):
        self.api_key = api_key or os.environ.get("NEBIUS_API_KEY")
        if not self.api_key:
            raise NebiusClientError("NEBIUS_API_KEY not set (pass api_key= or set the env var).")
        self.base_url = base_url or os.environ.get("NEBIUS_BASE_URL", DEFAULT_BASE_URL)
        self.model = model or os.environ.get("NEBIUS_MODEL", DEFAULT_MODEL)
        self.timeout = timeout

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
                json={"model": self.model, "messages": messages, "temperature": temperature},
            )
        if resp.status_code != 200:
            raise NebiusClientError(f"Nebius Token Factory returned {resp.status_code}: {resp.text}")

        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise NebiusClientError(f"Unexpected response shape from Nebius: {data}") from exc
