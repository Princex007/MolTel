"""Tests for the text helpers and publication-type classifier."""

from __future__ import annotations

from utils.evidence_types import classify_publication_types
from utils.text import condense


def test_condense_keeps_whole_sentences():
    text = (
        "First sentence is short. Second sentence is also short. "
        "Third sentence is much longer than the budget allows and gets dropped."
    )
    out = condense(text, max_chars=60)
    assert out == "First sentence is short. Second sentence is also short."


def test_condense_falls_back_to_hard_truncation():
    """A single run-on sentence still has to respect the budget."""
    out = condense("word " * 100, max_chars=40)
    assert len(out) <= 41
    assert out.endswith("…")


def test_condense_leaves_short_text_alone():
    assert condense("Already brief.", max_chars=320) == "Already brief."


def test_condense_collapses_whitespace():
    assert condense("Line one.\n\n   Line two.", max_chars=320) == "Line one. Line two."


def test_classify_prefers_strongest_publication_type():
    types = ["Journal Article", "Review", "Randomized Controlled Trial"]
    assert classify_publication_types(types) is not None
    assert classify_publication_types(types).value == "randomized_controlled_trial"


def test_classify_separates_preclinical_from_clinical():
    assert classify_publication_types(["In Vitro Study"]).value == "cellular"
    assert classify_publication_types(["Animal Study"]).value == "animal"
    assert classify_publication_types(["Review"]).value == "literature_review"


def test_classify_distinguishes_systematic_from_narrative_reviews():
    """A systematic method changes what a review can support, so it is its own class."""
    assert classify_publication_types(["Review"]).value == "literature_review"
    assert classify_publication_types(["Systematic Review"]).value == "systematic_review"
    assert classify_publication_types(["Meta-Analysis"]).value == "systematic_review"
    # 'Systematic Review' also contains 'review' — the systematic rule must win.
    assert classify_publication_types(["Journal Article", "Systematic Review"]).value == (
        "systematic_review"
    )


def test_classify_separates_non_evidence_record_types():
    """Editorials, case reports and notices are not studies and must not be counted as one."""
    assert classify_publication_types(["Letter", "Editorial"]).value == "editorial"
    assert classify_publication_types(["Case Reports"]).value == "case_report"
    assert classify_publication_types(["Published Erratum"]).value == "correction_or_retraction"
    assert classify_publication_types(["Retracted Publication"]).value == "correction_or_retraction"
    # A retraction notice outranks the study type of the record it concerns.
    assert classify_publication_types(
        ["Randomized Controlled Trial", "Retracted Publication"]
    ).value == "correction_or_retraction"


def test_classify_returns_none_for_unknown_types():
    """Unknown types stay unclassified instead of being defaulted to 'review'."""
    assert classify_publication_types(["Letter", "Editorial"]) is not None
    assert classify_publication_types(["Journal Article", "Research Support"]) is None
    assert classify_publication_types([]) is None
