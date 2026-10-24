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

import hashlib
import json
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import dotenv_values

from anticassiopeia.llm.nebius_client import NebiusClientError

_ENV = dotenv_values(".env")
_DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1"
_DEFAULT_MODEL = "openai/gpt-oss-120b"
#: Public alias of _DEFAULT_MODEL, for callers (e.g. run_test1.py's
#: run_provenance() call) that need to record the real default without
#: importing a leading-underscore "private" name across modules.
DEFAULT_MODEL_NAME = _DEFAULT_MODEL


def new_run_id() -> str:
    """One short, unique id per harness invocation (shared across every row
    that run produces), not per-row -- see run_provenance()'s own docstring
    for why this matters."""
    return uuid.uuid4().hex[:12]


def git_commit_hash() -> str:
    """FOUND BUG (external review): raw result rows had no way to tell which
    code version produced them -- repeated pivot runs reuse the same ~80
    claim IDs under different model variants with no way to tell runs apart
    except file order. Best-effort: a dirty/missing git checkout (e.g. a
    packaged artifact with no .git) must not crash a real run over a
    provenance nicety."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5,
            cwd=str(Path(__file__).parent.parent),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def claims_hash(claims: list[dict]) -> str:
    """Short hash of the EXACT claim set a batch ran against -- not a path
    to a manifest FILE, which wouldn't survive a pilot run against an
    ad hoc subset (e.g. the Nemotron pivot's select_pilot() samples) or a
    manifest regenerated after the fact. Hashes the claims' own content
    (sorted by claim_id for a stable hash regardless of iteration order),
    so two rows sharing this hash are PROVABLY running the identical claim
    set, not just a file with the same name."""
    canonical = json.dumps(sorted(claims, key=lambda c: c["claim_id"]), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


def run_provenance(claims: list[dict], model: str) -> dict:
    """FOUND BUG (external review): stress_test/results/*_raw.jsonl rows had
    no run_id, model ID, timestamp, commit, or manifest/claim-set hash --
    repeated pilot runs reuse the same ~80 claim IDs under different model
    variants with no way to tell rows from DIFFERENT runs apart except file
    order, which breaks the moment two runs get interleaved or a file is
    hand-edited. Computed ONCE per run_batch()/run_codeexec_batch() call
    (not per-row -- commit/claims_hash/run_id are constant across one run;
    only the per-row timestamp genuinely varies) and merged into every row.
    Going forward only, per the task: not backfilled into historical files."""
    return {
        "run_id": new_run_id(),
        "model": model,
        "commit": git_commit_hash(),
        "claims_hash": claims_hash(claims),
    }


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()

# Nebius Token Factory pricing for openai/gpt-oss-120b, as given in this task's
# own rule 5 — not re-derived, not looked up, used exactly as specified.
_INPUT_COST_PER_M = 0.15
_OUTPUT_COST_PER_M = 0.60

# Nemotron pricing on Nebius Token Factory, as of 2026-10-24 — sourced from
# third-party cost-estimator pages (nebius.com/prices-ai-studio is a
# JS-rendered page a static fetch can't read; this project tried and
# couldn't get the official table directly — see the Nemotron pivot's own
# cost report for that attempt). Cross-checked across 2 independent
# aggregators for Nano (agreed exactly); Super/Ultra each confirmed by one
# aggregator type across 2 separate searches, not independently
# cross-checked against Nebius's own page. Used as a working estimate for
# cost REPORTING only — the actual $ spent is always computed from the real
# `usage` field the API returns (real token counts), so a wrong price here
# would misstate the dollar figure but never cause an actual overspend
# beyond what real tokens actually cost at whatever the true rate is.
NEMOTRON_PRICING_PER_M: dict[str, tuple[float, float]] = {
    "nvidia/Nemotron-3-Ultra-550b-a55b": (1.00, 3.00),
    "nvidia/nemotron-3-super-120b-a12b": (0.30, 0.90),
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B": (0.06, 0.24),
    # Exact model ID confirmed live against GET /v1/models (2026-10-24) --
    # "Nemotron-3_5-Lightning" with an underscore, NOT "3.5" with a dot (that
    # string belongs to a different model, nvidia/Nemotron-3.5-Super-VL, which
    # is NOT this one). Pricing same tier as Nano (also third-party-sourced,
    # same caveat as the others above).
    "nvidia/Nemotron-3_5-Lightning": (0.06, 0.24),
}

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

    def record(
        self, prompt_tokens: int, completion_tokens: int, *, input_cost_per_m: float = _INPUT_COST_PER_M,
        output_cost_per_m: float = _OUTPUT_COST_PER_M,
    ) -> float:
        cost = (prompt_tokens / 1e6) * input_cost_per_m + (completion_tokens / 1e6) * output_cost_per_m
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

    def __init__(
        self,
        tracker: UsageTracker,
        timeout: float = 60.0,
        budget_usd: float = BUDGET_HARD_STOP_USD,
        model: str | None = None,
        input_cost_per_m: float | None = None,
        output_cost_per_m: float | None = None,
        max_tokens: int = 16384,
    ):
        self.api_key = _ENV.get("NEBIUS_API_KEY")
        if not self.api_key:
            raise RuntimeError("NEBIUS_API_KEY not loaded from .env via dotenv_values().")
        self.base_url = _ENV.get("NEBIUS_BASE_URL") or _DEFAULT_BASE_URL
        # Explicit `model` param takes priority over NEBIUS_MODEL/.env, so a caller
        # (e.g. the Nemotron pivot's side-by-side comparison) can run two different
        # models in the SAME process without touching .env between them -- unlike
        # before, where the only way to change the model was the env var, no caller
        # of this class ever actually needed that until now.
        self.model = model or _ENV.get("NEBIUS_MODEL") or _DEFAULT_MODEL
        # Pricing defaults to the gpt-oss-120b constants (this class's original,
        # only-ever-used-for-gpt-oss-120b behavior) unless the caller states
        # otherwise -- NEVER inferred from `self.model`'s name, so a caller that
        # forgets to pass pricing for a non-default model gets an honestly WRONG
        # dollar figure using the wrong model's price, not a silently-guessed one
        # from a name-matching table that could drift out of sync.
        self.input_cost_per_m = input_cost_per_m if input_cost_per_m is not None else _INPUT_COST_PER_M
        self.output_cost_per_m = output_cost_per_m if output_cost_per_m is not None else _OUTPUT_COST_PER_M
        self.timeout = timeout
        self.tracker = tracker
        self.budget_usd = budget_usd
        # Same fix as nebius_client.py's DEFAULT_MAX_TOKENS, mirrored here since
        # this class intentionally duplicates that method rather than wrapping it
        # -- applies equally to whichever model this instance is pointed at.
        self.max_tokens = max_tokens

    async def complete(self, prompt: str, *, system: str | None = None, temperature: float = 0.2) -> str:
        if self.tracker.total_cost_usd >= self.budget_usd:
            raise BudgetExceededError(
                f"Running spend ${self.tracker.total_cost_usd:.4f} already at/over the "
                f"${self.budget_usd:.2f} hard stop — refusing to make another live call."
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
                json={"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": self.max_tokens},
            )
        latency = time.monotonic() - start

        if resp.status_code != 200:
            raise NebiusClientError(f"Nebius Token Factory returned {resp.status_code}: {resp.text}")

        data = resp.json()
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        cost = self.tracker.record(
            prompt_tokens, completion_tokens,
            input_cost_per_m=self.input_cost_per_m, output_cost_per_m=self.output_cost_per_m,
        )

        if self.tracker.total_cost_usd >= BUDGET_HARD_STOP_USD:
            # Let THIS call's result through (it already happened and was paid
            # for), but the next complete() call will refuse before spending more.
            pass

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise NebiusClientError(f"Unexpected response shape from Nebius: {data}") from exc
        if not isinstance(content, str):
            # FOUND during the Nemotron pivot's pilot runs (see
            # stress_test/results/NEMOTRON_PIVOT_REPORT.md): a reasoning-capable
            # model can spend its whole token budget on hidden thinking content,
            # leaving `content` literally null -- same fix as
            # anticassiopeia/llm/nebius_client.py's complete(), mirrored here
            # since this class intentionally duplicates that method rather than
            # wrapping it (see module docstring).
            finish_reason = data["choices"][0].get("finish_reason")
            raise NebiusClientError(
                f"Nebius response had no usable content (got {content!r}, finish_reason="
                f"{finish_reason!r}) — likely truncated by the token limit: {data!r}"
            )
        return content
