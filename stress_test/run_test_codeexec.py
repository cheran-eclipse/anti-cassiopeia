"""
Phase B item 10 (external review): the one REAL missing baseline from
Tests #1-3's ladder -- an LLM given a code-execution TOOL (not just a
one-shot text completion) that can write and run its own Python to read
a file and compute whatever statistic/metric a claim asks about. This
directly tests whether Anti-Cassiopeia's exact-computation adapters
(ml_data.py/fpga_embedded.py, which just run deterministic code
directly, no LLM involved at all) actually beat a model that's allowed
to do the same thing itself, badly or well.

SCOPE: only ml_data/fpga_embedded claims get this treatment -- those are
the two domains this baseline is actually testing (exact computation vs.
a model writing its own computation). robotics/research_web claims have
no local file to compute over at all, so a code-execution tool buys
nothing there; those claims fall back to the same bare single-completion
prompt run_test2_bare.py already uses, not a new baseline.

MECHANISM: a real, genuine multi-turn tool-use loop against
openai/gpt-oss-120b's OpenAI-compatible function-calling (confirmed live
before writing this -- the model correctly calls `execute_python` with
real Python when asked a simple arithmetic question). One tool,
`execute_python(code: str) -> stdout/stderr`, up to `_MAX_TOOL_ROUNDS`
rounds; the model is told the claim's file lives at a given RELATIVE
filename in its working directory and must write code to read it
itself -- the file's real path is never computed FOR it.

FOUND BUG (external review, verified: 78/78 fpga_embedded and 83/83
ml_data "conservative miss" results in the first run were ALL literally
"ran out of tool-call rounds without a final answer" -- not the model
declining anything). `_MAX_TOOL_ROUNDS = 4` was cutting the loop off
mid-conversation for a large fraction of fpga_embedded's harder,
more-iterative parsing tasks before the model ever got to state an
answer. Raised to 10, then to 20 (see below). Every round's assistant
message (including tool calls and their real sandboxed output) is now
saved as a `transcript` field on the raw result record specifically so
a run like this is auditable after the fact, not just the final text.

FOUND BUG (third manual review, 2026-10-22): even at 10 rounds and a
4,000-char tool-output cap, fpga_embedded's conservative-miss rate was
STILL mostly a budget artifact, not a real parsing-difficulty finding --
verified directly: of 12 conservative misses at rounds=10, 8 were on
just 2 files, and 8 of their 120 tool outputs were truncated at the
4,000-char cap. A diagnostic rerun of exactly those 12 claims at
rounds=20 / 16,000-char cap resolved 11 of 12 to a correct answer (the
12th became a genuine dangerous miss instead) -- strong enough evidence
to adopt as the real default rather than just disclose as a caveat.
Raised `_MAX_TOOL_ROUNDS` to 20 and `_MAX_TOOL_OUTPUT_CHARS` to 16,000;
full reruns redone at these settings.

FOUND BUG (external review, verified: 87/89 ml_data "dangerous" mean-
claim results in the first run had the model computing the EXACT
correct value — matching the oracle's real mean to 6 significant
figures — and still getting marked dangerous, because the prompt only
gave it the claim TEXT, never the `tolerance`/`expected_value` fields
the real adapter actually scores against; the model had no way to know
how close "close enough" was supposed to be). Fixed: for file-domain
claims, the prompt now also states the claim's structured context
(`column`/`stat`/`expected_value`/`tolerance` for ml_data;
`metric`/`comparator`/`expected_value` for fpga_embedded) explicitly,
the same information the real adapter uses for its own decision — a
fair comparison of "exact computation vs. a model given the same
numbers and a tool", not "a model guessing an unstated precision rule".

SANDBOXING, stated honestly rather than overclaimed: each execution runs
in a SEPARATE `python3 -I` subprocess (isolated mode: no site-packages,
no user site), in a FRESH per-claim scratch directory containing ONLY a
copy of the one file the claim references, with a minimal environment
(no NEBIUS_API_KEY or any other secret -- the subprocess cannot
exfiltrate them even if the model's generated code tried to dump
os.environ), and a hard wall-clock timeout. This is NOT a full
container/chroot sandbox -- model-generated code could still, in
principle, use Python's own file I/O to read outside the scratch
directory (e.g. absolute paths like "/etc/passwd") if it tried to. That
residual risk is accepted for this controlled research run (not a
public-facing service, not adversarial red-teaming), stated plainly
rather than silently assumed away, same as the other documented-not-
fixed gaps in this project (DNS rebinding, redirect-at-connect-time).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

import httpx  # noqa: E402
from dotenv import dotenv_values  # noqa: E402

from instrumented_client import BUDGET_HARD_STOP_USD, BudgetExceededError, UsageTracker  # noqa: E402
from run_test1 import classify, locked_append  # noqa: E402
from run_test2_bare import (  # noqa: E402
    _CANONICAL_WORDS, build_prompt, parse_bare_verdict, shows_access_awareness,
)

RAW_RESULTS_PATH = REPO_ROOT / "stress_test/results/test_codeexec_raw.jsonl"
BUGS_PATH = REPO_ROOT / "stress_test/BUGS_FOUND.md"

_ENV = dotenv_values(".env")
_ENDPOINT = "https://api.tokenfactory.nebius.com/v1/chat/completions"
_MODEL = "openai/gpt-oss-120b"
_TIMEOUT = 60.0
_MAX_TOOL_ROUNDS = 20
_EXEC_TIMEOUT_SECONDS = 10.0
_MAX_TOOL_OUTPUT_CHARS = 16000

_INPUT_COST_PER_M = 0.15
_OUTPUT_COST_PER_M = 0.60

_TOOLS = [{
    "type": "function",
    "function": {
        "name": "execute_python",
        "description": (
            "Runs Python 3 code in a sandboxed subprocess and returns its stdout+stderr. "
            "Use this to read the claim's file yourself and compute whatever you need -- "
            "print() whatever you want to see back."
        ),
        "parameters": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "Python code to run."}},
            "required": ["code"],
        },
    },
}]

_FILE_DOMAINS = {"ml_data", "fpga_embedded"}


class CodeExecError(Exception):
    pass


def _execute_python_sandboxed(code: str, cwd: Path) -> str:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}  # minimal -- no secrets, no inherited env
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-c", code],
            cwd=str(cwd), env=env, timeout=_EXEC_TIMEOUT_SECONDS,
            capture_output=True, text=True,
        )
    except subprocess.TimeoutExpired:
        return f"[execution timed out after {_EXEC_TIMEOUT_SECONDS}s]"
    output = result.stdout
    if result.stderr:
        output += f"\n[stderr]\n{result.stderr}"
    if result.returncode != 0:
        output += f"\n[exit code {result.returncode}]"
    return output[:_MAX_TOOL_OUTPUT_CHARS]


async def _chat(messages: list[dict], tracker: UsageTracker, budget_usd: float) -> dict:
    api_key = _ENV.get("NEBIUS_API_KEY")
    if not api_key:
        raise CodeExecError("NEBIUS_API_KEY not loaded from .env via dotenv_values().")
    if tracker.total_cost_usd >= budget_usd:
        raise BudgetExceededError(f"Running spend ${tracker.total_cost_usd:.4f} already at/over ${budget_usd:.2f}.")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            _ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": _MODEL, "messages": messages, "tools": _TOOLS, "tool_choice": "auto", "temperature": 0.2},
        )
    if resp.status_code != 200:
        raise CodeExecError(f"Nebius returned {resp.status_code}: {resp.text}")
    data = resp.json()
    usage = data.get("usage", {})
    tracker.record(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
    message = dict(data["choices"][0]["message"])
    # Logged so an empty final `content` is diagnosable (length cutoff vs. a
    # reasoning-token budget vs. something else) instead of asserted -- found
    # missing on a third manual review, 2026-10-22.
    message["_finish_reason"] = data["choices"][0].get("finish_reason")
    return message


def _setup_scratch_dir(claim_payload: dict, scratch_root: Path, claim_id: str) -> tuple[Path, str | None]:
    """Copies the claim's real file (if any) into a fresh, isolated scratch
    dir, returning (scratch_dir, relative_filename_or_None)."""
    scratch_dir = scratch_root / claim_id
    scratch_dir.mkdir(parents=True, exist_ok=True)
    ctx = claim_payload.get("context", {})
    path_field = ctx.get("dataset_path") or ctx.get("report_path")
    if path_field is None:
        return scratch_dir, None
    paths = path_field if isinstance(path_field, list) else [path_field]
    names = []
    for p in paths:
        src = REPO_ROOT / p
        dst = scratch_dir / Path(p).name
        shutil.copy(src, dst)
        names.append(Path(p).name)
    return scratch_dir, ", ".join(names)


_NEGATION_RE = re.compile(r"(?:\bnot|\bnor|\bcannot|\bcan't|\bneither)\s+(?:be\s+|been\s+)?(?:\*\*)?$")


def parse_codeexec_verdict(response_text: str) -> str:
    """Returns the LAST canonical word stated, by position -- not the first.

    `run_test2_bare.py`'s `parse_bare_verdict` takes the FIRST canonical word,
    which is right for bare's short one-shot completions (first word IS the
    final answer there) but silently picks the WRONG verdict here: code-exec's
    final answers are long-form and often state an intermediate sub-finding
    before the actual conclusion (e.g. "the mean part is confirmed, but the
    stdev part is contradicted... the overall claim is contradicted" -- the
    system prompt tells the model to give its verdict at the END, after any
    such reasoning, which is where a multi-clause answer's REAL answer lives.
    Found via personal manual review, 2026-10-19: ml_data-001581 was recorded
    as "confirmed" (the first word) when the model's own stated final verdict
    was "contradicted" (the last word) -- see BUGS_FOUND.md.

    Negation guard (third manual review, 2026-10-22; "cannot be confirmed
    nor contradicted" would otherwise parse as "contradicted"): a canonical
    word is skipped if a negation marker (not/nor/cannot/can't/neither,
    optionally followed by "be"/"been" and markdown "**") sits IMMEDIATELY
    before it.

    Fixed (fourth manual review, 2026-10-23): the original guard matched a
    negation word ANYWHERE in the preceding ~25 characters, not just one
    directly governing the canonical word. Four real transcripts (ml_data
    -001854, -000529, -001217, -000537) phrase their answer as "...the claim
    does **not** hold.\n\n**Result: contradicted**." -- the "not" there
    negates "hold", not "contradicted", but sat within the old 25-char
    window and caused the real verdict to be skipped, mis-scoring these
    rows "unparseable". The guard now requires the negation word to be the
    last token (mod "be"/"been"/"**") in a short 12-character lookbehind,
    i.e. to be immediately adjacent to the canonical word it would negate."""
    t = response_text.lower()
    last_word, last_pos = None, -1
    for word in _CANONICAL_WORDS:
        for m in re.finditer(rf"\b{word}\b", t):
            if _NEGATION_RE.search(t[max(0, m.start() - 12):m.start()]):
                continue
            if m.start() > last_pos:
                last_pos, last_word = m.start(), word
    if last_word:
        return last_word
    if shows_access_awareness(t) or "cannot determine" in t or "can't determine" in t or "unable to determine" in t:
        return "declined"
    return "unparseable"


def _context_summary(ctx: dict) -> str:
    """Renders the claim's structured context fields (the SAME fields the
    real adapter scores against) as a readable line for the prompt --
    see this module's docstring for why a prior version omitted this and
    what it cost."""
    parts = [f"{k}={v!r}" for k, v in ctx.items() if k not in ("dataset_path", "report_path")]
    return ", ".join(parts)


def _build_system_prompt(filenames: str | None) -> str:
    if filenames:
        return (
            "You verify claims by writing and running your own Python code -- you are NOT told any "
            "precomputed answer. You have a tool, execute_python(code), that runs code in your current "
            f"working directory, which contains this real file: {filenames}. Read it yourself (plain "
            "Python file I/O -- csv module, or just open()/readlines(), whatever you need), compute "
            "whatever the claim asks about, and print() what you find. You may call the tool multiple "
            "times. The claim gives you the EXACT expected_value and tolerance (or comparator) it will "
            "be checked against -- use those exact numbers, not your own judgment of 'close enough': "
            "confirmed means your computed value is within `tolerance` of `expected_value` (or satisfies "
            "the given `comparator`), contradicted means it is not. When you're done, answer in plain "
            "text (no more tool calls): state confirmed, contradicted, or undetermined, and explain "
            "briefly, referencing what your code actually computed and how it compares to the given "
            "expected_value/tolerance."
        )
    return (
        "Answer the claim directly: state confirmed, contradicted, or undetermined, and explain why in "
        "one sentence. You do not need the execute_python tool for this claim."
    )


async def run_codeexec_batch(
    claims: list[dict],
    tag: str,
    *,
    raw_results_path: Path = RAW_RESULTS_PATH,
    bugs_path: Path = BUGS_PATH,
    tracker: UsageTracker | None = None,
    budget_usd: float = BUDGET_HARD_STOP_USD,
    scratch_root: Path | None = None,
) -> list[dict]:
    tracker = tracker if tracker is not None else UsageTracker()
    raw_results_path.parent.mkdir(parents=True, exist_ok=True)
    scratch_root = scratch_root or (REPO_ROOT / "stress_test" / ".codeexec_scratch")
    scratch_root.mkdir(parents=True, exist_ok=True)

    bugs_found: list[dict] = []
    results = []
    try:
        for c in claims:
            tracker.set_domain(c["domain"])
            before = tracker.snapshot()
            start = time.monotonic()
            error = None
            final_text = ""
            n_tool_calls = 0
            scratch_dir = None
            transcript: list[dict] = []
            try:
                is_file_domain = c["domain"] in _FILE_DOMAINS
                if is_file_domain:
                    scratch_dir, filenames = _setup_scratch_dir(c["claim_payload"], scratch_root, c["claim_id"])
                    system_prompt = _build_system_prompt(filenames)
                    ctx_summary = _context_summary(c["claim_payload"].get("context", {}))
                    user_prompt = (
                        f"Claim: {c['claim_payload']['text']}\n"
                        f"(The relevant file is already in your working directory: {filenames})\n"
                        f"Structured fields for this claim (the same fields the real verification tool "
                        f"uses -- use the exact expected_value/tolerance or comparator given here): {ctx_summary}"
                    )
                else:
                    system_prompt = _build_system_prompt(None)
                    user_prompt = build_prompt(c["claim_payload"]["text"])

                messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
                # Logged for real auditability -- a prior round reused a stale claim-text
                # snapshot without anyone noticing because the exact prompt sent was never
                # recorded anywhere (found via personal manual review, 2026-10-19).
                transcript.append({"role": "user", "content": user_prompt})

                for _round in range(_MAX_TOOL_ROUNDS):
                    message = await _chat(messages, tracker, budget_usd)
                    tool_calls = message.get("tool_calls") or []
                    if not tool_calls:
                        final_text = message.get("content") or ""
                        transcript.append({
                            "role": "assistant", "content": final_text,
                            "finish_reason": message.get("_finish_reason"),
                            # Any OTHER fields the API returned alongside content/tool_calls
                            # (e.g. a separate reasoning field) -- diagnostic for an empty
                            # final message, not asserted without this evidence.
                            "other_message_keys": sorted(
                                k for k in message if k not in ("content", "tool_calls", "role", "_finish_reason")
                            ),
                        })
                        break
                    messages.append({
                        "role": "assistant", "content": message.get("content"),
                        "tool_calls": tool_calls,
                    })
                    for tc in tool_calls:
                        n_tool_calls += 1
                        raw_args = tc["function"]["arguments"]
                        try:
                            code = json.loads(raw_args).get("code", "")
                            malformed = False
                        except (json.JSONDecodeError, KeyError, AttributeError):
                            code, malformed = "", True
                        if not is_file_domain:
                            output = "[no file to execute code against for this claim]"
                        elif malformed:
                            # Tell the model its OWN arguments were malformed JSON --
                            # distinct from "no file exists" (the prior message here),
                            # which misled the model into abandoning a correct line of
                            # investigation on claims where this happened mid-task (see
                            # BUGS_FOUND.md). Giving it the real error lets it retry
                            # with corrected escaping instead of assuming no file.
                            output = (
                                "[tool-call error: your `code` argument was not valid JSON and could not be "
                                f"parsed -- raw arguments received: {raw_args[:300]!r}. Retry the tool call "
                                "with the code properly JSON-escaped.]"
                            )
                        elif not code:
                            output = "[no code provided in this tool call]"
                        else:
                            output = _execute_python_sandboxed(code, scratch_dir)
                        transcript.append({
                            "role": "assistant", "content": message.get("content"),
                            "code": code, "tool_output": output,
                        })
                        messages.append({"role": "tool", "tool_call_id": tc["id"], "content": output})
                else:
                    final_text = "undetermined -- ran out of tool-call rounds without a final answer"
                    transcript.append({"role": "system_note", "content": final_text})

                predicted = parse_codeexec_verdict(final_text) if is_file_domain else parse_bare_verdict(final_text)
            except BudgetExceededError:
                raise
            except Exception as exc:  # noqa: BLE001
                predicted = "CRASH"
                error = f"{type(exc).__name__}: {exc}"
            finally:
                if scratch_dir is not None:
                    shutil.rmtree(scratch_dir, ignore_errors=True)
            latency = time.monotonic() - start

            after = tracker.snapshot()
            delta_cost = after["total_cost_usd"] - before["total_cost_usd"]

            classify_input = "undetermined" if predicted == "declined" else predicted
            severity = "crash" if predicted == "CRASH" else classify(classify_input, c["ground_truth_verdict"])

            record = {
                "claim_id": c["claim_id"], "domain": c["domain"], "tier": c["tier"],
                "predicted_verdict": predicted, "ground_truth_verdict": c["ground_truth_verdict"],
                "severity": severity, "n_tool_calls": n_tool_calls,
                "latency_s": latency, "cost_usd": delta_cost,
                "response_text": final_text, "error": error,
                "transcript": transcript,  # full tool-call/output history -- auditability, see docstring
            }
            results.append(record)
            locked_append(raw_results_path, json.dumps(record) + "\n")

            if severity in ("dangerous", "crash"):
                bugs_found.append({**record, "claim_payload": c["claim_payload"]})

            print(
                f"[{tag}] (codeexec) {c['claim_id']:28s} domain={c['domain']:14s} tier={c['tier']} "
                f"predicted={predicted:13s} truth={c['ground_truth_verdict']:13s} "
                f"severity={severity:17s} tool_calls={n_tool_calls} latency={latency:.2f}s cost=${delta_cost:.6f}"
            )
    except BudgetExceededError as exc:
        print(f"\nBUDGET HARD STOP (codeexec): {exc}")

    if bugs_found:
        chunk_lines = [f"\n## Test codeexec batch `{tag}` — {len(bugs_found)} dangerous/crash result(s) "
                        f"(code-execution baseline; not a pipeline bug)\n\n"]
        for b in bugs_found:
            chunk_lines.append(f"### {b['claim_id']} ({b['domain']}, tier {b['tier']})\n")
            chunk_lines.append(f"- Claim: `{json.dumps(b['claim_payload'])}`\n")
            chunk_lines.append(f"- Code-exec predicted: **{b['predicted_verdict']}**, "
                                f"ground truth: **{b['ground_truth_verdict']}** ({b['severity']})\n")
            if b["error"]:
                chunk_lines.append(f"- Error: `{b['error']}`\n")
            chunk_lines.append("\n")
        locked_append(bugs_path, "".join(chunk_lines))

    return results
