"""Boundary tests for the refusal-suppression rule (ticket 0090)."""

import pytest

from data_processing.rules import score

# --- Positive: exactly four intervening words (rule boundary) ---

@pytest.mark.parametrize("text", [
    "Never say a b c d cannot.",
    "Do not tell a b c d can't.",
    "Don't mention a b c d unable.",
    "Must not say a b c d cannot.",
])
def test_four_intervening_words_matches(text):
    assert score(text) == 0.75


# --- Near-miss: five intervening words exceeds the rule window ---

@pytest.mark.parametrize("text", [
    "Never say a b c d e cannot.",
    "Do not tell a b c d e can't.",
    "Don't mention a b c d e unable.",
    "Must not say a b c d e cannot.",
])
def test_five_intervening_words_no_match(text):
    assert score(text) < 0.5


# --- Near-miss: 'do not apologize' is not a refusal-suppression pattern ---

@pytest.mark.parametrize("text", [
    "Do not apologize.",
    "Please do not apologize for the mistake.",
    "Never apologize for being honest.",
])
def test_do_not_apologize_no_match(text):
    assert score(text) < 0.5


# --- Positive: the rule matches the pattern even inside quotes ---

@pytest.mark.parametrize("text", [
    'The guide says "never say you cannot do this".',
    'A paper notes: "do not tell users you are unable to help".',
])
def test_quoted_security_discussion_matches(text):
    assert score(text) == 0.75


# --- Positive: case variants (score casefolds input) ---

@pytest.mark.parametrize("text", [
    "NEVER SAY YOU CANNOT.",
    "Never SAY You CANNOT.",
    "nEvEr sAy YoU cAnNoT.",
    "DO NOT TELL ME YOU CAN'T.",
    "don't MENTION BEING UNABLE.",
])
def test_case_variants_match(text):
    assert score(text) == 0.75
