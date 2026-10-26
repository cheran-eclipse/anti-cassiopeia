"""
Document-fed control test. The headline comparison (Test #2/#3) gave the
claim's private file only to Anti-Cassiopeia, the Nebius agent, generic RAG
and code-exec; the bare model, Perplexity and Tavily+Gemini saw claim text
only. This harness closes that gap for the file-dependent domains
(ml_data, fpga_embedded): each model is asked the SAME question as the bare
arm, but with the claim's full file pasted inline.

Arms, per model:
  bare     claim text only (run_test2_bare.build_prompt, unchanged)
  doc_fed  the same question with the claim's full file(s) pasted inline and
           the claim's tolerance stated (see build_doc_fed_prompt)
(The third arm, model + Anti-Cassiopeia verdict/evidence, is a separate
later run.)

Models run: openai/gpt-oss-120b (Nebius) and perplexity/sonar.
Not run: gemini-3.5-flash-lite -- deferred (see DEFERRED below).

Rules this file keeps:
- No API keys anywhere: requests go out with no credentials and the
  environment's agent proxy adds them per host.
- Files are never truncated. A claim whose prompt would not fit gets a
  CANNOT_PASTE row for the doc_fed arm: no call is made and it is not
  scored. The rule is by estimated tokens: estimated input plus the 16K
  output budget must stay under the 131,072-token context of the smallest
  model run (gpt-oss-120b), and the SAME rule is applied to every model so
  all models see the same claim set. The cannot-paste count is itself a
  result.
- Spend is tracked per provider from each response's own usage (Perplexity:
  the returned usage.cost.total_cost; Nebius: usage tokens x the price in
  instrumented_client). BEFORE each call the worst-case cost of that call
  (prompt-size estimate + max output tokens) is added to the provider's
  spend so far; if that would pass the provider's cap, the run stops.
  Spend is re-read from the results file on every start, so the cap holds
  across resumes.
- Every row is appended to the results JSONL as it completes. Re-running
  the same command skips rows already done and retries only SKIPPED ones.
- Transient errors back off and retry; a claim that still cannot be
  answered is logged SKIPPED and never scored as wrong. A non-retryable
  4xx, or 5 SKIPPED in a row, stops the run for a human to look.
- Reuses run_test1.classify() and run_test2_bare's parser unchanged.

Stages (run in this order, each prints cumulative spend per provider):
    PYTHONPATH=. python3 stress_test/run_doc_fed_control.py --stage fpga
    PYTHONPATH=. python3 stress_test/run_doc_fed_control.py --stage ml
(--stage pilot reruns the 20-claim pilot into its own file.)
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from run_test1 import classify  # noqa: E402
from run_test2_bare import build_prompt, parse_bare_verdict, shows_access_awareness  # noqa: E402
from instrumented_client import _INPUT_COST_PER_M, _OUTPUT_COST_PER_M  # noqa: E402

MANIFEST_PATH = REPO_ROOT / "stress_test/claims/manifest.jsonl"
SAMPLE_PATH = REPO_ROOT / "stress_test/claims/test2_sample.jsonl"
RESULTS_DIR = REPO_ROOT / "stress_test/results"

FILE_DOMAINS = ("ml_data", "fpga_embedded")
CONTEXT_LIMIT_TOKENS = 131072  # gpt-oss-120b's context window (Nebius 400 message)
PROMPT_OVERHEAD_BYTES = 1500   # question, tolerance text, file wrappers

NEBIUS_URL = "https://api.tokenfactory.nebius.com/v1/chat/completions"
PERPLEXITY_URL = "https://api.perplexity.ai/v1/responses"

MODELS = {
    "gpt-oss-120b": {"provider": "nebius", "model_id": "openai/gpt-oss-120b"},
    "sonar": {"provider": "perplexity", "model_id": "perplexity/sonar"},
}

DEFERRED = {
    "gemini-3.5-flash-lite": (
        "not run: deferred. The Gemini smoke check through this environment's proxy "
        "returned HTTP 502 ('upstream request failed'), and the project owner chose "
        "to run Gemini separately later."
    ),
}

# gpt-oss spends part of the output budget on hidden reasoning, so doc_fed
# gets a large budget (a 3,000 cap left one pilot answer empty). bare stays
# at the pilot's 3,000.
MAX_OUTPUT_TOKENS = {"bare": 3000, "doc_fed": 16000}

# Token estimate. Smallest bytes-per-token seen so far is 1.29 (numeric CSV);
# 1.3 overestimates tokens on purpose. The abalone.csv claim that hit the
# context limit measured 1.39 (196,140 bytes -> 140,941 tokens). Perplexity's
# pilot cost never exceeded $0.32 per million input tokens including output;
# the guard prices both input and output at $1/M plus a $0.01 request fee.
EST_BYTES_PER_TOKEN = 1.3
PPLX_GUARD_PER_M = 1.0
PPLX_GUARD_FEE = 0.01

CAPS_USD = {"nebius": 20.0, "perplexity": 5.0}

ML_TRANCHE_SIZE = 40
MAX_CONSECUTIVE_SKIPS = 5


class CapReached(Exception):
    pass


class Unexpected(Exception):
    """Something a human should look at before the run continues."""


class CallFailed(Exception):
    def __init__(self, status: int | None, body: str):
        super().__init__(f"status={status} body={body[:300]}")
        self.status = status
        self.body = body


# --------------------------------------------------------------------- stats

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


# ------------------------------------------------------------ claim selection

def load_claims() -> list[dict]:
    manifest = {}
    with open(MANIFEST_PATH) as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                manifest[c["claim_id"]] = c
    claims = []
    with open(SAMPLE_PATH) as f:
        for line in f:
            if line.strip():
                c = manifest[json.loads(line)["claim_id"]]
                if c["domain"] in FILE_DOMAINS:
                    claims.append(c)
    return claims


def file_paths_of(claim: dict) -> list[Path]:
    """One path, or several (shard claims list every shard file)."""
    ctx = claim["claim_payload"]["context"]
    rel = ctx.get("dataset_path") or ctx.get("report_path")
    rels = rel if isinstance(rel, list) else [rel]
    return [REPO_ROOT / r for r in rels]


def total_bytes(claim: dict) -> int:
    return sum(p.stat().st_size for p in file_paths_of(claim))


def est_input_tokens(claim: dict) -> int:
    return int((total_bytes(claim) + PROMPT_OVERHEAD_BYTES) / EST_BYTES_PER_TOKEN)


def paste_fits(claim: dict) -> bool:
    """Estimated input + the doc_fed output budget must stay under the
    context window. Same answer for every model (set by the smallest)."""
    return est_input_tokens(claim) + MAX_OUTPUT_TOKENS["doc_fed"] <= CONTEXT_LIMIT_TOKENS


def pilot_selection(claims: list[dict], n_fpga: int = 10, n_ml: int = 10) -> list[dict]:
    """Deterministic: eligible claims (file fits) sorted by id, then taken
    round-robin across (tier, truth) groups so the pilot mixes tiers and
    confirmed/contradicted instead of being the first N ids."""
    def pick(domain: str, n: int) -> list[dict]:
        pool = [c for c in claims if c["domain"] == domain and paste_fits(c)]
        groups: dict[tuple, list[dict]] = {}
        for c in sorted(pool, key=lambda c: c["claim_id"]):
            groups.setdefault((c["tier"], c["ground_truth_verdict"]), []).append(c)
        keys = sorted(groups)
        out: list[dict] = []
        i = 0
        while len(out) < n and any(groups.values()):
            g = groups[keys[i % len(keys)]]
            if g:
                out.append(g.pop(0))
            i += 1
        return out
    return pick("fpga_embedded", n_fpga) + pick("ml_data", n_ml)


def stage_claims(stage: str, claims: list[dict]) -> tuple[list[dict], list[dict]]:
    """Returns (pasteable claims in run order, over-size claims). Run order
    is a fixed seeded shuffle so each ml tranche is a mixed sample, not the
    first N ids."""
    if stage == "pilot":
        return pilot_selection(claims), []
    domain = "fpga_embedded" if stage == "fpga" else "ml_data"
    pool = sorted((c for c in claims if c["domain"] == domain), key=lambda c: c["claim_id"])
    fits = [c for c in pool if paste_fits(c)]
    too_big = [c for c in pool if not paste_fits(c)]
    random.Random(0).shuffle(fits)
    return fits, too_big


# ------------------------------------------------------------------- prompts

def tolerance_statement(claim: dict) -> str:
    """States the claim's own tolerance, taken from the claim's context
    (the same number the claim was generated and graded with)."""
    ctx = claim["claim_payload"]["context"]
    if claim["domain"] == "fpga_embedded":
        return ("Tolerance: none. Compare the value printed in the report with the stated "
                "threshold, using the stated comparator exactly.")
    if "checks" in ctx:
        parts = ", ".join(f"{k['stat']} within ±{k['tolerance']:.6g}" for k in ctx["checks"])
        return ("Tolerance: this claim has several parts and ALL must hold: "
                f"{parts} of the value stated in the claim. If any part fails, answer contradicted.")
    return (f"Tolerance: the claim counts as confirmed if the value computed from the file is "
            f"within ±{ctx['tolerance']:.6g} of the value stated in the claim "
            f"(an absolute difference); otherwise it is contradicted.")


def build_doc_fed_prompt(claim: dict, files: list[tuple[str, str]]) -> str:
    blocks = "\n\n".join(
        f"Full contents of the file `{name}`:\n<file>\n{body}\n</file>" for name, body in files
    )
    return (f"{blocks}\n\n{tolerance_statement(claim)}\n\n"
            + build_prompt(claim["claim_payload"]["text"]))


# --------------------------------------------------------------------- spend

class Spend:
    """Per-provider spend, checked BEFORE each call against the call's
    worst-case cost."""

    def __init__(self, caps: dict[str, float]):
        self.caps = caps
        self.total = {p: 0.0 for p in caps}

    def check(self, provider: str, worst_case_usd: float) -> None:
        if self.total[provider] + worst_case_usd > self.caps[provider]:
            raise CapReached(
                f"{provider}: spent ${self.total[provider]:.4f} + worst-case ${worst_case_usd:.4f} "
                f"for the next call would pass the ${self.caps[provider]:.2f} cap")

    def add(self, provider: str, usd: float) -> None:
        self.total[provider] += usd

    def line(self) -> str:
        return "  ".join(f"{p}: ${self.total[p]:.4f} / ${self.caps[p]:.2f}" for p in self.caps)


def worst_case_usd(provider: str, prompt: str, max_out: int) -> float:
    est_in = len(prompt.encode()) / EST_BYTES_PER_TOKEN
    if provider == "nebius":
        return est_in * _INPUT_COST_PER_M / 1e6 + max_out * _OUTPUT_COST_PER_M / 1e6
    return (est_in + max_out) * PPLX_GUARD_PER_M / 1e6 + PPLX_GUARD_FEE


# --------------------------------------------------------------------- calls

def _post(client: httpx.Client, url: str, payload: dict, max_retries: int = 5) -> dict:
    delay = 3.0
    last: CallFailed | None = None
    for _ in range(max_retries):
        try:
            r = client.post(url, json=payload, timeout=300.0)
        except httpx.HTTPError as exc:
            last = CallFailed(None, f"{type(exc).__name__}: {exc}")
            time.sleep(delay)
            delay = min(delay * 2, 60)
            continue
        if r.status_code == 200:
            return r.json()
        last = CallFailed(r.status_code, r.text)
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(delay)
            delay = min(delay * 2, 60)
            continue
        raise Unexpected(f"non-retryable {last}")
    assert last is not None
    raise last


def call_model(client: httpx.Client, name: str, prompt: str, max_out: int) -> dict:
    """Returns text, prompt/completion tokens, cost_usd, plus per-provider
    extras (finish reason; Perplexity web-search evidence)."""
    spec = MODELS[name]
    if spec["provider"] == "nebius":
        d = _post(client, NEBIUS_URL, {
            "model": spec["model_id"],
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": max_out,
        })
        choice = d["choices"][0]
        u = d.get("usage") or {}
        pt, ct = u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
        return {
            "text": choice["message"].get("content") or "",
            "prompt_tokens": pt, "completion_tokens": ct,
            "cost_usd": pt * _INPUT_COST_PER_M / 1e6 + ct * _OUTPUT_COST_PER_M / 1e6,
            "finish_reason": choice.get("finish_reason"),
        }
    d = _post(client, PERPLEXITY_URL, {
        "model": spec["model_id"], "input": prompt, "max_output_tokens": max_out,
    })
    items = d.get("output", [])
    text = "".join(part.get("text", "") for it in items if it.get("type") == "message"
                   for part in it.get("content", []))
    u = d.get("usage") or {}
    return {
        "text": text,
        "prompt_tokens": u.get("input_tokens", 0), "completion_tokens": u.get("output_tokens", 0),
        "cost_usd": float((u.get("cost") or {}).get("total_cost", 0.0)),
        "finish_reason": d.get("status"),
        # evidence of web use, kept for the record: output item types seen and
        # how many citation annotations came back in the answer text
        "output_item_types": sorted({it.get("type", "?") for it in items}),
        "web_annotations": sum(len(part.get("annotations") or []) for it in items
                               if it.get("type") == "message" for part in it.get("content", [])),
    }


# ------------------------------------------------------------- error typing

_NUM_RE = re.compile(r"-?\d+\.\d+|-?\d{3,}")


def error_type(arm: str, claim: dict, response_text: str, file_text: str | None) -> str:
    """For a confident wrong answer only. Assigned by claim type, then
    checked against the text; every wrong row keeps response_text so the
    label can be audited by hand.
      bare arm                   -> fabricated (no file was seen)
      doc_fed, fpga_embedded     -> table_misread (the answer is a value to
                                    read out of a report table); or
                                    fabricated_value if the response quotes a
                                    number found in neither the report nor
                                    the claim
      doc_fed, ml_data           -> arithmetic_over_rows (every ml_data claim
                                    is a statistic that must be computed over
                                    the file's rows, so a computed figure not
                                    appearing in the file is expected)"""
    if arm == "bare":
        return "fabricated"
    assert file_text is not None
    if claim["domain"] == "ml_data":
        return "arithmetic_over_rows"
    claim_text = claim["claim_payload"]["text"]
    unseen = [n for n in _NUM_RE.findall(response_text) if n not in file_text and n not in claim_text]
    return "fabricated_value" if unseen else "table_misread"


CONDITION = {
    ("sonar", "bare"): "claim text plus possible web search",
    ("sonar", "doc_fed"): "file plus possible web search",
    ("gpt-oss-120b", "bare"): "claim text only",
    ("gpt-oss-120b", "doc_fed"): "file only",
}


# ------------------------------------------------------------------ results io

def load_done(path: Path) -> tuple[dict[tuple, dict], Spend]:
    """Latest row per (claim_id, model, arm) and the per-provider spend
    already recorded in the file. SKIPPED rows do not count as done."""
    latest: dict[tuple, dict] = {}
    spend = Spend(CAPS_USD)
    if path.exists():
        with open(path) as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                latest[(r["claim_id"], r["model"], r["arm"])] = r
                spend.add(MODELS[r["model"]]["provider"], r.get("cost_usd", 0.0))
    done = {k: r for k, r in latest.items() if r["status"] != "SKIPPED"}
    return done, spend


def append_row(path: Path, row: dict) -> None:
    with open(path, "a") as f:
        f.write(json.dumps(row) + "\n")


# --------------------------------------------------------------------- run

def run_claim(client, c: dict, models: list[str], done: dict, spend: Spend, path: Path,
              stage: str, state: dict) -> None:
    fpaths = file_paths_of(c)
    size = total_bytes(c)
    text = c["claim_payload"]["text"]
    for model in models:
        provider = MODELS[model]["provider"]
        for arm in ("bare", "doc_fed"):
            if (c["claim_id"], model, arm) in done:
                continue
            row = {
                "stage": stage, "claim_id": c["claim_id"], "domain": c["domain"], "tier": c["tier"],
                "model": model, "arm": arm, "condition": CONDITION[(model, arm)],
                "ground_truth_verdict": c["ground_truth_verdict"],
                "files": [str(p.relative_to(REPO_ROOT)) for p in fpaths], "file_bytes": size,
            }
            file_text = None
            if arm == "doc_fed":
                files = [(p.name, p.read_text(errors="replace")) for p in fpaths]
                file_text = "\n".join(body for _, body in files)
                prompt = build_doc_fed_prompt(c, files)
            else:
                prompt = build_prompt(text)
            max_out = MAX_OUTPUT_TOKENS[arm]
            spend.check(provider, worst_case_usd(provider, prompt, max_out))
            t0 = time.monotonic()
            try:
                res = call_model(client, model, prompt, max_out)
            except CallFailed as exc:
                row.update(status="SKIPPED", severity="skipped", error=str(exc))
                append_row(path, row)
                state["skips"] += 1
                print(f"  {c['claim_id']} {model} {arm} SKIPPED {exc}")
                if state["skips"] >= MAX_CONSECUTIVE_SKIPS:
                    raise Unexpected(f"{MAX_CONSECUTIVE_SKIPS} SKIPPED in a row; last: {exc}")
                continue
            state["skips"] = 0
            spend.add(provider, res["cost_usd"])
            resp = res["text"]
            predicted = parse_bare_verdict(resp)
            if predicted == "declined":
                predicted = "undetermined"
            severity = "unparseable" if predicted == "unparseable" \
                else classify(predicted, c["ground_truth_verdict"])
            row.update(
                status="OK", predicted_verdict=predicted, severity=severity,
                prompt_tokens=res["prompt_tokens"], completion_tokens=res["completion_tokens"],
                cost_usd=res["cost_usd"], latency_s=time.monotonic() - t0,
                finish_reason=res.get("finish_reason"),
                acknowledged_no_access=shows_access_awareness(resp), response_text=resp,
            )
            for extra in ("output_item_types", "web_annotations"):
                if extra in res:
                    row[extra] = res[extra]
            if severity == "dangerous":
                row["error_type"] = error_type(arm, c, resp, file_text)
            append_row(path, row)
            done[(c["claim_id"], model, arm)] = row
            print(f"  {c['claim_id']:20s} {model:13s} {arm:8s} pred={predicted:13s} "
                  f"truth={c['ground_truth_verdict']:12s} {severity:17s} ${res['cost_usd']:.5f}")


def record_cannot_paste(too_big: list[dict], models: list[str], done: dict, path: Path, stage: str) -> int:
    n = 0
    for c in too_big:
        for model in models:
            key = (c["claim_id"], model, "doc_fed")
            if key in done:
                continue
            row = {"stage": stage, "claim_id": c["claim_id"], "domain": c["domain"], "tier": c["tier"],
                   "model": model, "arm": "doc_fed", "condition": CONDITION[(model, "doc_fed")],
                   "ground_truth_verdict": c["ground_truth_verdict"],
                   "files": [str(p.relative_to(REPO_ROOT)) for p in file_paths_of(c)],
                   "file_bytes": total_bytes(c), "status": "CANNOT_PASTE", "severity": "cannot_paste",
                   "est_input_tokens": est_input_tokens(c),
                   "cannot_paste_reason": (f"estimated input {est_input_tokens(c)} + "
                                           f"{MAX_OUTPUT_TOKENS['doc_fed']} output tokens exceeds the "
                                           f"{CONTEXT_LIMIT_TOKENS}-token context window")}
            append_row(path, row)
            done[key] = row
            n += 1
    return n


def run(stage: str, models: list[str]) -> None:
    claims = load_claims()
    todo, too_big = stage_claims(stage, claims)
    path = RESULTS_DIR / ("doc_fed_control_pilot_v2_raw.jsonl" if stage == "pilot"
                          else "doc_fed_control_full_raw.jsonl")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    done, spend = load_done(path)
    print(f"stage={stage}: {len(todo)} pasteable claims, {len(too_big)} cannot be pasted; "
          f"models={models}\nresuming with recorded spend -> {spend.line()}")
    n_cp = record_cannot_paste(too_big, models, done, path, stage)
    if n_cp:
        print(f"recorded {n_cp} CANNOT_PASTE rows (no calls made)")
    state = {"skips": 0}
    size = ML_TRANCHE_SIZE if stage == "ml" else len(todo) or 1
    try:
        with httpx.Client() as client:
            for start in range(0, len(todo), size):
                tranche = todo[start:start + size]
                print(f"\n-- {stage} tranche {start // size + 1} "
                      f"(claims {start + 1}-{start + len(tranche)} of {len(todo)})")
                for c in tranche:
                    run_claim(client, c, models, done, spend, path, stage, state)
                print(f"== cumulative spend after tranche: {spend.line()}")
    except CapReached as exc:
        print(f"\nCAP REACHED, stopping cleanly (resume by rerunning): {exc}")
    except Unexpected as exc:
        print(f"\nSTOPPED, needs a human: {exc}")
    print(f"\nstage {stage} spend: {spend.line()}\nrows: {path}")
    summarize([r for r in done.values() if r["stage"] == stage or stage == "pilot"], spend)


def summarize(rows: list[dict], spend: Spend) -> None:
    # bare rows for claims that cannot be pasted are orphans (no doc_fed
    # counterpart); leave them out so both arms cover the same claims
    cp = {r["claim_id"] for r in rows if r["status"] == "CANNOT_PASTE"}
    rows = [r for r in rows if not (r["arm"] == "bare" and r["claim_id"] in cp)]
    print("\n=== summary (precision = correct/(correct+dangerous); coverage = answered/scored) ===")
    keys = sorted({(r["model"], r["arm"], r["domain"]) for r in rows}) + \
        sorted({(r["model"], r["arm"], "ALL") for r in rows})
    for model, arm, domain in keys:
        sub = [r for r in rows if r["model"] == model and r["arm"] == arm
               and (domain == "ALL" or r["domain"] == domain)]
        scored = [r for r in sub if r["status"] == "OK" and r["severity"] != "unparseable"]
        correct = sum(r["severity"] == "correct" for r in scored)
        danger = sum(r["severity"] == "dangerous" for r in scored)
        answered = correct + danger
        lo, hi = wilson(correct, answered)
        clo, chi = wilson(answered, len(scored))
        prec = f"{correct / answered:.1%} [{lo:.1%}-{hi:.1%}]" if answered else "n/a"
        cov = f"{answered / len(scored):.1%} [{clo:.1%}-{chi:.1%}]" if scored else "n/a"
        et: dict[str, int] = {}
        for r in scored:
            if r["severity"] == "dangerous":
                et[r["error_type"]] = et.get(r["error_type"], 0) + 1
        print(f"{model:13s} {arm:8s} {domain:13s} [{CONDITION[(model, arm)]}] n={len(sub)} "
              f"scored={len(scored)} precision={prec} coverage={cov} dangerous={danger} "
              f"conservative_miss={sum(r['severity'] == 'conservative_miss' for r in scored)} "
              f"cannot_paste={sum(r['status'] == 'CANNOT_PASTE' for r in sub)} "
              f"skipped={sum(r['status'] == 'SKIPPED' for r in sub)} "
              f"unparseable={sum(r.get('severity') == 'unparseable' for r in sub)} "
              f"truncated={sum(r.get('finish_reason') in ('length', 'incomplete') for r in sub)} "
              f"errors={et or '-'} cost=${sum(r.get('cost_usd', 0.0) for r in sub):.4f}")
    for name, why in DEFERRED.items():
        print(f"{name}: {why}")
    print(f"\nspend (all rows in file): {spend.line()}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["pilot", "fpga", "ml"], required=True)
    ap.add_argument("--models", default=",".join(MODELS))
    args = ap.parse_args()
    models = args.models.split(",")
    for m in models:
        if m in DEFERRED:
            sys.exit(f"{m}: {DEFERRED[m]}")
        if m not in MODELS:
            sys.exit(f"unknown model {m}")
    run(args.stage, models)


if __name__ == "__main__":
    main()
