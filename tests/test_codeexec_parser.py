"""Unit tests for stress_test/run_test_codeexec.py's verdict parser --
added on a third manual review (2026-10-22) after it was flagged as
fragile in principle (no test previously exercised it directly).

Four more added on a fourth manual review (2026-10-23): the negation
guard added in the third review was itself too broad -- it matched a
negation word anywhere in the preceding ~25 characters instead of one
directly governing the canonical word, so it misparsed real model
output. These four strings are copied verbatim (truncated to the
relevant tail) from stress_test/results/test3_codeexec_raw.jsonl's
ml_data-001854, ml_data-000529, ml_data-001217 and ml_data-000537."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "stress_test"))

from run_test_codeexec import parse_codeexec_verdict  # noqa: E402


def test_takes_the_last_canonical_word_not_the_first():
    text = "the mean part is confirmed, but the stdev part is contradicted -- overall, the claim is contradicted."
    assert parse_codeexec_verdict(text) == "contradicted"


def test_negated_canonical_word_is_not_mistaken_for_the_verdict():
    # Without the negation guard this misparses as "contradicted" (the last
    # literal canonical-word substring in the text) -- it must NOT.
    text = "Based on my analysis, this claim cannot be confirmed nor contradicted with the available data."
    assert parse_codeexec_verdict(text) != "contradicted"
    assert parse_codeexec_verdict(text) != "confirmed"


def test_negation_guard_does_not_blind_it_to_a_real_later_verdict():
    text = "It cannot be confirmed from a quick look, but after computing it directly, the result is contradicted."
    assert parse_codeexec_verdict(text) == "contradicted"


def test_plain_single_word_verdict_still_works():
    assert parse_codeexec_verdict("Confirmed.") == "confirmed"


def test_empty_response_is_unparseable():
    assert parse_codeexec_verdict("") == "unparseable"


def test_a_negation_not_governing_the_canonical_word_does_not_block_it():
    # "not" negates "hold", not "contradicted" -- it must not swallow the
    # real verdict just because it precedes it somewhere in the tail.
    text = (
        "The absolute difference exceeds the allowed tolerance, so the "
        "claim does **not** hold.\n\n**Result: contradicted**."
    )
    assert parse_codeexec_verdict(text) == "contradicted"


def test_ml_data_001854_real_transcript_tail():
    text = (
        "The claim expects a median of **400.0400000000001** with a "
        "tolerance of **1.0126**. Since 1012.6 differs from 400.04 by far "
        "more than the allowed tolerance, the claim does **not** hold.\n\n"
        "**Result: contradicted**."
    )
    assert parse_codeexec_verdict(text) == "contradicted"


def test_ml_data_000529_real_transcript_tail():
    text = (
        "claim expects a mean of **55.787979067261816** with a tolerance "
        "of **0.030525319378174546**. The absolute difference (≈ 25.26) "
        "far exceeds the allowed tolerance, so the claim does **not** "
        "hold.\n\n**Result: contradicted**."
    )
    assert parse_codeexec_verdict(text) == "contradicted"


def test_ml_data_001217_real_transcript_tail():
    text = (
        "the claim expects a mean of **104.24138297872341** with a "
        "tolerance of **4.532234042553192**.  \n\nThe difference (≈ 13.6) "
        "is far larger than the allowed tolerance, so the claim does "
        "**not** hold.\n\n**Result: contradicted**."
    )
    assert parse_codeexec_verdict(text) == "contradicted"


def test_ml_data_000537_real_transcript_tail():
    text = (
        "The claim expects a mean of **35.104117284900724** with a "
        "tolerance of **1.5262659689087272**.  \n\nThe absolute difference "
        "(≈ 4.58) exceeds the allowed tolerance, so the claim does "
        "**not** hold.\n\n**Result: contradicted**."
    )
    assert parse_codeexec_verdict(text) == "contradicted"
