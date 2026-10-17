"""
Live deployment surface.

One endpoint: POST /verify, body = {"text": ..., "domain": ..., "context": {...}}.
Returns a full Verdict (state, confidence, evidence, reasoning, missing).

This is intentionally small. The point of Anti-Cassiopeia as infrastructure
is that other developers integrate against this one contract regardless of
which domain they're checking against — the surface should stay stable
even as domain adapters get real implementations behind it.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from anticassiopeia.core import Claim, UnknownDomainError, VerificationEngine
from anticassiopeia.domains import default_domains

app = FastAPI(
    title="Anti-Cassiopeia",
    description="Domain-agnostic verification: confirmed / contradicted / undetermined — never a guess dressed up as certainty.",
    version="0.1.0",
)

engine = VerificationEngine(domains=default_domains())


class VerifyRequest(BaseModel):
    text: str
    domain: str
    context: dict = {}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "domains": sorted(engine._domains)}


@app.post("/verify")
async def verify(req: VerifyRequest) -> dict:
    claim = Claim(text=req.text, domain=req.domain, context=req.context)
    try:
        verdict = await engine.verify(claim)
    except UnknownDomainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return verdict.to_dict()
