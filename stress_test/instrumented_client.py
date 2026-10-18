"""
A stress-test-only instrumented Nebius client. Lives entirely in
stress_test/ — does NOT edit anticassiopeia/llm/nebius_client.py. Mirrors
that module's real HTTP call (same endpoint, same key, same model,
resolved the same way) but ALSO captures the real `usage` field the
Nebius Token Factory API returns (prompt_tokens/completion_tokens),
which the production client discards after extracting just the message
content — production has no reason to track cost, this harness does.

Duck-typed to the same `complete(prompt, *, system=None, temperature=0.2)
-> str` interface the production adapters expect, so it can be injected
via the EXISTING constructor params (`RoboticsAdapter(client=...)`,
`ResearchWebAdapter(client=...)`) that were built for exactly this kind
of test substitution.

SECRET HANDLING: the API key is loaded via python-dotenv's
dotenv_values() only (never os.environ, never `source .env`, never
printed/logged) and is never written to any report file.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx
from dotenv import dotenv_values

_ENV = dotenv_values(".env")
_DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1"
_DEFAULT_MODEL = "openai/gpt-oss-120b"

# Nebius Token Factory pricing for openai/gpt-oss-120b, as given in this task's
# own rule 5 — not re-derived, not looked up, used exactly as specified.
_INPUT_COST_PER_M = 0.15
_OUTPUT_COST_PER_M = 0.60

BUDGET_HARD_STOP_USD = 6.00


class BudgetExceededError(Exception):
    """Raised when a call would push running spend at/over the hard stop."""


@dataclass
class UsageTracker:
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cost_usd: float = 0.0
    call_count: int = 0
    by_domain_cost: dict = field(default_factory=dict)
    _current_domain: str = "unknown"

    def set_domain(self, domain: str) -> None:
        self._current_domain = domain

    def record(self, prompt_tokens: int, completion_tokens: int) -> float:
        cost = (prompt_tokens / 1e6) * _INPUT_COST_PER_M + (completion_tokens / 1e6) * _OUTPUT_COST_PER_M
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_cost_usd += cost
        self.call_count += 1
        self.by_domain_cost[self._current_domain] = self.by_domain_cost.get(self._current_domain, 0.0) + cost
        return cost

    def snapshot(self) -> dict:
        return {
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_cost_usd": self.total_cost_usd,
            "call_count": self.call_count,
        }


class InstrumentedNebiusClient:
    """One instance shared across all adapters/claims in a run, so
    `tracker` accumulates a true running total for the hard-stop check."""

    def __init__(self, tracker: UsageTracker, timeout: float = 60.0):
        self.api_key = _ENV.get("NEBIUS_API_KEY")
        if not self.api_key:
            raise RuntimeError("NEBIUS_API_KEY not loaded from .env via dotenv_values().")
        self.base_url = _ENV.get("NEBIUS_BASE_URL") or _DEFAULT_BASE_URL
        self.model = _ENV.get("NEBIUS_MODEL") or _DEFAULT_MODEL
        self.timeout = timeout
        self.tracker = tracker

    async def complete(self, prompt: str, *, system: str | None = None, temperature: float = 0.2) -> str:
        if self.tracker.total_cost_usd >= BUDGET_HARD_STOP_USD:
            raise BudgetExceededError(
                f"Running spend ${self.tracker.total_cost_usd:.4f} already at/over the "
                f"${BUDGET_HARD_STOP_USD:.2f} hard stop — refusing to make another live call."
            )

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        start = time.monotonic()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "messages": messages, "temperature": temperature},
            )
        latency = time.monotonic() - start

        if resp.status_code != 200:
            raise RuntimeError(f"Nebius Token Factory returned {resp.status_code}: {resp.text}")

        data = resp.json()
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        cost = self.tracker.record(prompt_tokens, completion_tokens)

        if self.tracker.total_cost_usd >= BUDGET_HARD_STOP_USD:
            # Let THIS call's result through (it already happened and was paid
            # for), but the next complete() call will refuse before spending more.
            pass

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"Unexpected response shape from Nebius: {data}") from exc
