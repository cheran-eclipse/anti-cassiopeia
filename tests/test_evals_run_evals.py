"""
Tests evals/run_evals.py's `_needs_live_key()` -- the FOUND BUG fix (external
review): `docker build`'s own smoke-test step runs this script with no
NEBIUS_API_KEY/TAVILY_API_KEY available at all (.env is deliberately not
copied into the image), and every robotics case plus every research_web
mode-2 case was silently resolving to the wrong verdict and FAILING the
build, not skipping -- see run_evals.py's own docstring on that function.
"""

from evals.run_evals import _needs_live_key


def _case(domain: str, context: dict | None = None) -> dict:
    return {"claim": {"text": "x", "domain": domain, "context": context or {}}}


def test_robotics_always_needs_a_live_key():
    assert _needs_live_key(_case("robotics")) is True
    assert _needs_live_key(_case("robotics", {"depth_m": 500})) is True


def test_research_web_mode2_needs_a_live_key():
    assert _needs_live_key(_case("research_web")) is True
    assert _needs_live_key(_case("research_web", {"quote": "something"})) is True


def test_research_web_mode1_does_not_need_a_live_key():
    """Mode 1 (an explicit "url") never calls the LLM client -- plain
    HTML-fetch + verbatim-quote check only."""
    assert _needs_live_key(_case("research_web", {"url": "https://example.com", "quote": "x"})) is False


def test_ml_data_and_fpga_embedded_never_need_a_live_key():
    assert _needs_live_key(_case("ml_data")) is False
    assert _needs_live_key(_case("fpga_embedded")) is False
