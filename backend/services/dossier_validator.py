"""Pre-publication validation of a generated dossier against its own records.

The narrative fields are written by the model, so no prompt can guarantee they
agree with the registry, the label set, or the arithmetic the tables are built
from. This module checks the finished text against the structured records that
produced it and reports every disagreement it finds.

Two severities:
  error    — the claim contradicts a retrieved record, or states a number no
             retrieved record supports. Publication is blocked and the reader sees
             the discrepancy.
  warning  — the claim is not contradicted but rests on weaker evidence than its
             wording implies, or the retrieval behind it is incomplete.

Nothing here rewrites the narrative and nothing supplies a value the source did
not state: an unverifiable claim is labelled for review, never repaired.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable, Optional

from models.schemas import (
    ClinicalTrial,
    Contradiction,
    Dossier,
    EvidenceItem,
    EvidenceStrength,
    QueryAttributionSummary,
    ResearchGap,
    SourceStatus,
    TrialAnalytics,
    ValidationFinding,
    ValidationReport,
)

_NARRATIVE_FIELDS = (
    "executive_summary",
    "mechanism",
    "therapeutic_evidence",
    "literature_summary",
    "clinical_development",
    "safety",
    "evidence_gaps",
    "research_opportunities",
)

RULES = (
    "TRIAL_PHASE_MISMATCH",
    "TRIAL_STATUS_MISMATCH",
    "TRIAL_INTERACTION_UNSUPPORTED",
    "TRIAL_DURATION_CONTRADICTS_CLAIM",
    "TRIAL_POPULATION_MISMATCH",
    "NUMERIC_CLAIM_UNSOURCEDED",
    "COUNT_NOT_IN_RETRIEVAL",
    "FABRICATED_IDENTIFIER",
    "REPORTING_SIGNAL_OVERCLAIM",
    "ABSENCE_OVERCLAIM",
    "LABEL_CLAIM_WITHOUT_PRODUCT",
    "PRECLINICAL_HUMAN_RELEVANCE",
    "SURROGATE_ENDPOINT_OVERCLAIM",
    "ARITHMETIC_UNRECONCILED",
    "RETRIEVAL_INCOMPLETE",
    "SOURCE_NOT_CONSULTED",
    "DESIGN_UNSPECIFIED",
    "RECORD_PROVENANCE_MISSING",
)

_NCT = re.compile(r"\bNCT\d{8}\b", re.I)
_PMID = re.compile(r"\bPMID[:\s]+(\d{5,9})\b", re.I)
_DOI = re.compile(r"\bDOI[:\s]+([0-9]{2,4}[.\-/][A-Za-z0-9._()/\-]{3,})\b", re.I)
_ANY_IDENTIFIER = re.compile(
    r"\b(?:NCT\d{6,10}|PMID[:\s]?\d{5,9}|DOIs?[:\s]\S+|PMC\d{5,9}|CID[:\s]?\d{3,12}|"
    r"(?:NDA|ANDA|BLA)\d{4,6}|[A-Z][0-9][A-Z0-9]{3,8})\b"
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")

_PERCENT = re.compile(r"(?:[~≈]\s*)?\b\d{1,3}(?:\.\d+)?\s*%")
# A duration is written as a figure or as a word, and prose uses both for the
# same endpoint ("at 68 weeks", "over a six month period").
_NUMERAL = r"\d{1,3}|[a-z]{2,9}(?:-[a-z]{2,9})?"
_DURATION = re.compile(
    r"\b(?:at|after|over|by|during|in|to|of)\s+(?:roughly |approximately |about |mean |up to )?"
    r"(?:a |an )?("
    + _NUMERAL + r")\s*(week|month|year)s?\b",
    re.I,
)
_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}


def _numeral(text: str) -> Optional[int]:
    """Read a count written as digits or as an English number, or refuse it."""
    token = text.strip().casefold()
    if token.isdigit():
        return int(token)
    if "-" in token:
        parts = [_NUMBER_WORDS.get(p) for p in token.split("-")]
        if all(p for p in parts) and len(parts) == 2:
            return parts[0] + parts[1]
        return None
    return _NUMBER_WORDS.get(token)


_COUNT_NOUN = re.compile(
    r"\b(\d{1,4})\s*\+?\s*(?:[\w'&()-]+\s+){0,3}?"
    r"(trials?|studies|publications?|records?|articles?|papers?|reports?|analyses|"
    r"cohorts?|case[s]?|labels?)\b",
    re.I,
)
_COUNT_PREFIX = re.compile(r"\bn\s*=\s*(\d{1,4})\s*\+?", re.I)
_PHASE = re.compile(r"\b(?:early\s+)?phase\s+(?:[1-4](?:\s*/\s*[1-4])?|III|IV|II|I\b)", re.I)
# A registry time frame names the visit at which an endpoint was read. The
# registry writes it both ways ("Weeks 4, 8, and 12" and "to week 104"), and a
# list of visits shares one unit, so both orders and their separators are read.
# Values convert to days so "68 weeks" and "six months" can be compared.
_TIME_POINT = re.compile(
    r"\b(week|month|year|day)s?\s+(\d{1,3}(?:\s*(?:,|and|to|-)\s*\d{1,3})*)"
    r"|\b(\d{1,3})\s*(week|month|year|day)s?\b",
    re.I,
)
_TIME_UNIT_DAYS = {"week": 7.0, "month": 30.44, "year": 365.25, "day": 1.0}
_INTERACTION_PARTY = re.compile(
    r"(?:interactions?|co-?administered|co-?administration|combined|combination|"
    r"compared|administered|given)\s+(?:with|between|and|to|of)\s+"
    r"([A-Za-z][A-Za-z0-9\-&'() ]{2,60}?)(?=[,.;]|\s+\(|$)",
    re.I,
)
# "between X and Y" is one capture; each side has to be a registered intervention.
_PARTY_SPLIT = re.compile(r"\s*(?:,|;|/|\band\b|\bwith\b|\bplus\b)\s*", re.I)
# A period stated as a compound modifier ("a 20-year follow-up") is as much a
# duration claim as one introduced by a preposition.
_DURATION_COMPOUND = re.compile(
    r"\b(" + _NUMERAL + r")[\s-](week|month|year)s?[\s-]"
    r"(follow|treatment|therapy|term|period|duration|exposure|extension|run)\w*",
    re.I,
)
# A sentence that cites a record and names a period states that period of that
# record whether or not a preposition introduces it ("a six month result").
_DURATION_BARE = re.compile(
    r"\b(" + _NUMERAL + r")\s*(week|month|year)s?\b",
    re.I,
)

# Registry statuses this module compares wording against. Longest phrase first so
# "active, not recruiting" is never read as a claim of "recruiting".
_STATUS_PHRASES: tuple[tuple[str, str], ...] = (
    ("active, not recruiting", "ACTIVE_NOT_RECRUITING"),
    ("enrolling by invitation", "ENROLLING_BY_INVITATION"),
    ("not yet recruiting", "NOT_YET_RECRUITING"),
    ("temporarily not available", "TEMPORARILY_NOT_AVAILABLE"),
    ("recruiting", "RECRUITING"),
    ("completed", "COMPLETED"),
    ("terminated", "TERMINATED"),
    ("withdrawn", "WITHDRAWN"),
    ("suspended", "SUSPENDED"),
)

_PHARMACOVIGILANCE = (
    "faers", "vigibase", "spontaneous report", "disproportionality",
    "pharmacovigilance", "adverse event report", "signal detection",
    "post-marketing report", "reported events",
)
_CAUSAL_OR_INCIDENCE = (
    "causes", "caused", "causing", "confirms", "confirmed", "proves", "proof",
    "incidence", "rate of", "risk of", "leads to", "results in", "increased risk",
    "demonstrates that", "showed that", "linked to", "responsible for",
)
_NON_CAUSAL_HEDGE = (
    "cannot establish", "can not establish", "does not establish", "not proof",
    "not evidence of causality", "without establishing", "may reflect",
    "cannot be interpreted", "does not prove", "reporting alone", "not causal",
    "cannot infer", "no incidence",
)
_ABSENCE_PHRASES = (
    "no evidence exists", "there is no evidence", "no evidence has been",
    "has never been studied", "have never been studied", "has not been studied",
    "unstudied", "no studies have", "no trial has", "no trials exist",
    "nothing is known", "no data exist", "no published data", "never been investigated",
    "remains unexplored", "is not documented",
)
_LABEL_CLAIM = (
    "boxed warning", "black box", "contraindicat", "warning and precaution",
    "warnings and precautions", "label warning", "prescribing information",
    "indicated", "approved for",
)
_NON_HUMAN = (
    "rodent", "mouse", "mice", "rat", "animal model", "preclinical", "in vivo model",
    "cytotoxicity assay", "in vitro",
)
# A histological or biomarker reading is an outcome about tissue, not a clinical
# endpoint on a patient. Naming the surrogate does not establish the benefit.
_SURROGATE_OUTCOME = (
    "histological", "histology", "biopsy", "naslp", "fibrosis improvement",
    "steatohepatitis resolution", "biomarker", "surrogate endpoint", "imaging endpoint",
)
_CLINICAL_BENEFIT = (
    "proven", "demonstrated", "confirmed", "established", "reduces mortality",
    "prevents progression", "long-term benefit", "hard clinical outcome",
    "translated into", "results in fewer",
)
# "A hard clinical outcome was not assessed" draws the same distinction this rule
# asks for, so a denial in front of the benefit wording is not an overclaim.
_BENEFIT_DENIAL = re.compile(
    r"\b(?:not|no|never|cannot)\b[^.;]{0,40}\b(?:proven|proves|prove|demonstrated|"
    r"demonstrate|confirmed|confirm|established|establish|assessed|assess|"
    r"measured|evaluated|shown|showed)\b",
    re.I,
)
_POPULATION = re.compile(
    r"\b(\d{1,6})\s*(?:of\s+)?\s*(participants?|patients?|subjects?|enrolled|"
    r"individuals?|children|adults)\b",
    re.I,
)
_HUMAN_DOUBT = (
    "uncertain", "unclear", "not established", "unknown relevance",
    "has not been demonstrated", "may not translate", "human relevance",
    "no established association",
)
# A number that describes this retrieval, not the literature, is checked by the
# count rules instead, so a dose, a p-value or a hazard ratio is left alone.
_UNCHECKED_NUMBER = re.compile(
    r"\b(?:p\s*[<=]|hazard ratio|odds ratio|relative risk|mg|mcg|µg|ng/mL|"
    r"mmol|kg|cm|ml|IU|cycle|arm|site[s]?|centre[s]?|center[s]?)\b",
    re.I,
)


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_END.split(text or "") if part.strip()]


def _days(date_text: Optional[str]) -> Optional[int]:
    """Days since epoch for a full or partial ISO date, or None if unusable.

    Partial registry dates are placed at the middle of their month or year rather
    than padded to a fabricated day, and the span check tolerates that.
    """
    if not date_text:
        return None
    parts = str(date_text).strip().split("-")
    try:
        if len(parts) == 3:
            year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        elif len(parts) == 2:
            year, month, day = int(parts[0]), int(parts[1]), 15
        elif len(parts) == 1 and len(parts[0]) == 4:
            year, month, day = int(parts[0]), 7, 1
        else:
            return None
    except ValueError:
        return None
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return None
    year_shift = year - (1 if month <= 2 else 0)
    era = year_shift // 100
    yoe = year_shift - era * 100
    doy = (153 * (month + (-9 if month > 2 else 3)) + 2) // 5 + day - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 36525 + doe - 719468


def _finding(
    rule: str,
    severity: str,
    field: str,
    quote: str,
    expected: Optional[str] = None,
    observed: Optional[str] = None,
    source_ref: Optional[str] = None,
    correction: Optional[str] = None,
) -> ValidationFinding:
    return ValidationFinding(
        rule=rule,
        severity=severity,
        field=field,
        quote=" ".join(quote.split())[:300],
        expected=expected,
        observed=observed,
        source_ref=source_ref,
        suggested_correction=correction,
        status="fail",
        blocks_publication=severity == "error",
    )


class _Context:
    """Everything the rules compare text against, resolved once."""

    def __init__(
        self,
        trials: list[ClinicalTrial],
        evidence_identifiers: Iterable[str],
        products: Iterable[str],
        analytics: Optional[TrialAnalytics],
        strength: Optional[EvidenceStrength],
        attribution: Optional[QueryAttributionSummary],
        partial: bool = False,
    ) -> None:
        self.trials = {t.nct_id.upper(): t for t in trials}
        self.identifiers = {str(v).upper() for v in evidence_identifiers if v}
        self.identifiers |= set(self.trials)
        self.products = [p for p in (x.lower() for x in products) if p]
        self.analytics = analytics
        self.strength = strength
        self.attribution = attribution
        self.partial = partial
        self.allowed_counts = self._allowed_counts()

    def _allowed_counts(self) -> set[int]:
        allowed: set[int] = set()
        analytics, strength, attribution = self.analytics, self.strength, self.attribution
        if analytics:
            allowed |= {
                analytics.total_trials,
                analytics.ongoing_trials,
                analytics.trials_with_unreported_phase,
                analytics.enrolling_by_invitation_trials,
                analytics.recruiting_trials,
                analytics.currently_recruiting_trials,
            }
            allowed |= {bucket.count for bucket in analytics.trials_by_status}
            allowed |= {bucket.count for bucket in analytics.trials_by_phase}
            allowed |= {group.count for group in analytics.status_groups}
        if attribution and attribution.applicable:
            allowed |= {
                attribution.distinct_trials,
                attribution.direct_trials,
                attribution.comparator_or_combination_trials,
                attribution.query_specific_trials,
                attribution.related_not_named_trials,
                attribution.not_demonstrably_relevant_trials,
                attribution.distinct_intervention_names,
                attribution.distinct_investigational_candidates,
                attribution.placebo_or_sham_arms,
            }
            allowed |= {category.count for category in attribution.categories}
        if strength:
            allowed |= {
                strength.total_records,
                strength.publication_records,
                strength.regulatory_passages,
                strength.unclassified_count,
            }
            allowed |= {category.count for category in strength.categories}
            allowed |= {design.count for design in strength.study_design_counts}
        return {value for value in allowed if value}

    def known(self, token: str) -> bool:
        return token.upper() in self.identifiers


def _phase_agrees(trial: ClinicalTrial, claim: str) -> bool:
    """Whether a phase phrase in the narrative agrees with this record's phase.

    A registry value is never inferred from a title or an indication: only the
    digits the registry itself states can satisfy a claim.
    """
    registry = trial.phase or ""
    claimed = set(re.findall(r"[1-4]", claim))
    if not claimed:
        claimed = {
            {"I": "1", "II": "2", "III": "3", "IV": "4"}.get(token, "")
            for token in re.findall(r"\b(I{1,3}V?|IV)\b", claim.upper())
        } - {""}
    actual = set(re.findall(r"[1-4]", registry))
    if not actual or not claimed:
        # One side states no comparable phase: nothing to contradict.
        return True
    return claimed == actual


def _claimed_statuses(sentence: str) -> list[str]:
    """Every status this sentence words, in the order the phrases appear.

    "Recruiting or active trials include A, B and C" claims two states for the
    whole list, so a record matching either one is not contradicted by it.
    """
    lowered = sentence.lower()
    codes = [code for phrase, code in _STATUS_PHRASES if phrase in lowered]
    # Prose shortens "Active, not recruiting" to "active"; the word boundary keeps
    # "actively recruiting" from adding a state the sentence never claims.
    if re.search(r"\bactive\b", lowered):
        codes.append("ACTIVE_NOT_RECRUITING")
    return list(dict.fromkeys(codes))


def _registered_intervention(trial: ClinicalTrial, party: str) -> bool:
    party_words = {w for w in re.findall(r"[a-z0-9]+", party.casefold()) if len(w) > 3}
    if not party_words:
        return False
    for intervention in trial.interventions or []:
        haystack = set(re.findall(r"[a-z0-9]+", intervention.casefold()))
        if party_words & haystack:
            return True
    return False


def _party_words(party: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", party.casefold()) if len(w) > 3}


def _co_administered(trial: ClinicalTrial, parties: list[str]) -> bool:
    """Whether the registry files every one of these products in a single arm.

    Two products registered in different arms of the same record were given to
    different groups of participants. The record therefore states no study in
    which they met, and a title that lists both does not create one.
    """
    words = [_party_words(p) for p in parties]
    for group in trial.arm_groups:
        listed = [
            set(re.findall(r"[a-z0-9]+", name.casefold()))
            for name in group.intervention_names
        ]
        if all(any(w & arm for arm in listed) for w in words):
            return True
    return False


def _duration_contradiction(
    trial: ClinicalTrial, match: re.Match,
) -> Optional[tuple[str, str]]:
    """Whether a stated period could have been observed in the cited record.

    Only a claim LONGER than the registry's own study span is impossible, and only
    that is reported: a study can legitimately be reported at any of its own time
    points, and this module does not know which one the narrative meant.
    """
    value = _numeral(match.group(1))
    if value is None:
        return None
    unit = match.group(2).lower()
    claimed_days = value * {"week": 7.0, "month": 30.44, "year": 365.25}[unit]
    start = _days(trial.start_date)
    end = _days(trial.completion_date or trial.primary_completion_date)
    if start is None or end is None or end < start:
        return None
    span = float(end - start)
    if claimed_days <= span + 45:
        return None
    return (
        (
            f"{trial.nct_id} ran {span / 30.44:.1f} months by its own registry dates "
            f"({trial.start_date} to {trial.completion_date or trial.primary_completion_date})"
        ),
        (
            f"the narrative reports a {value}-{unit} result for this record"
        ),
    )


def _stated_time_points(trial: ClinicalTrial) -> set[float]:
    """Every time point this record says it read an outcome, in days.

    A registry time frame is the only statement of when an endpoint was measured,
    so these are the values a narrative duration can be checked against.
    """
    days: set[float] = set()
    for frame in trial.outcome_time_frames:
        for match in _TIME_POINT.finditer(frame):
            if match.group(1):
                unit = match.group(1).lower()
                numbers = re.findall(r"\d{1,3}", match.group(2))
            else:
                unit = match.group(4).lower()
                numbers = [match.group(3)]
            for number in numbers:
                days.add(int(number) * _TIME_UNIT_DAYS[unit])
    return {point for point in days if point > 0}


def _time_point_contradiction(
    trial: ClinicalTrial, match: re.Match
) -> Optional[tuple[str, str]]:
    """Whether a stated duration is one this record measured.

    Moving a result between time points changes which measurement is being
    reported: a 68-week reading is not a six-month reading, and neither the
    record nor any retrieved publication says the two are the same.
    """
    points = _stated_time_points(trial)
    if not points:
        return None
    value = _numeral(match.group(1))
    if value is None:
        return None
    unit = match.group(2).lower()
    claimed = value * _TIME_UNIT_DAYS[unit]
    if any(abs(claimed - point) <= max(10.0, claimed * 0.15) for point in points):
        return None
    weeks = ", ".join(
        str(int(round(point / _TIME_UNIT_DAYS["week"])))
        for point in sorted(points)
    )
    return (
        f"{trial.nct_id} reads its outcomes at week {weeks}, per its own time frames",
        f"the narrative reports a {value}-{unit} result for this record",
    )


def _narrative_fields(dossier: Optional[Dossier]) -> list[tuple[str, str]]:
    if dossier is None:
        return []
    fields = [(name, str(getattr(dossier, name) or "")) for name in _NARRATIVE_FIELDS]
    findings = dossier.contradictory_findings
    if findings:
        for index, item in enumerate(findings.contradictions):
            fields.append(
                (
                    f"contradictory_findings[{index}]",
                    " ".join(
                        part for part in (
                            item.claim, item.study_a, item.study_b,
                            item.possible_explanation,
                        ) if part
                    ),
                )
            )
    for index, gap in enumerate(dossier.research_gap_analysis):
        fields.append(
            (
                f"research_gap_analysis[{index}]",
                " ".join(
                    part for part in (
                        gap.question, gap.current_evidence, gap.uncertainty,
                        gap.why_it_matters, gap.next_step,
                    ) if part
                ),
            )
        )
    return fields


def _span_gap(a: tuple[int, int], b: tuple[int, int]) -> int:
    """Characters between two spans in the same sentence, 0 if they touch."""
    if a[1] <= b[0]:
        return b[0] - a[1]
    if b[1] <= a[0]:
        return a[0] - b[1]
    return 0


# A comma inside a parenthetical list of identifiers does not end the clause, so
# "Phase 3 trials (A, B)" stays one clause that both studies belong to.
_CLAUSE_END = re.compile(r"[;,](?![^(]*\))")


def _clause_bounds(sentence: str, position: int) -> tuple[int, int]:
    """The run of words a single phase claim can govern around `position`."""
    low = 0
    high = len(sentence)
    for match in _CLAUSE_END.finditer(sentence):
        if match.start() < position:
            low = match.end()
        else:
            high = match.start()
            break
    return low, high


def _check_sentence(
    findings: list[ValidationFinding],
    field: str,
    sentence: str,
    context: _Context,
) -> None:
    nct_ids = [match.group(0).upper() for match in _NCT.finditer(sentence)]
    cited = bool(_ANY_IDENTIFIER.search(sentence))

    for match in _PMID.finditer(sentence):
        if not context.known(f"PMID:{match.group(1)}"):
            findings.append(
                _finding(
                    "FABRICATED_IDENTIFIER", "error", field, sentence,
                    expected="a PMID belonging to a retrieved record",
                    observed=f"PMID:{match.group(1)}",
                    correction="Cite a record this search actually returned, or omit it.",
                )
            )

    for match in _DOI.finditer(sentence):
        if not context.known(f"DOI:{match.group(1)}"):
            findings.append(
                _finding(
                    "FABRICATED_IDENTIFIER", "error", field, sentence,
                    expected="a DOI belonging to a retrieved record",
                    observed=f"DOI:{match.group(1)}",
                    correction="Cite a record this search actually returned, or omit it.",
                )
            )

    for match in _NCT.finditer(sentence):
        nct = match.group(0).upper()
        if nct not in context.trials:
            findings.append(
                _finding(
                    "FABRICATED_IDENTIFIER", "error", field, sentence,
                    expected="an NCT ID among the trials this search retrieved",
                    observed=nct,
                    correction=(
                        "Cite a study this retrieval returned, or state the finding "
                        "without an identifier and mark it for review."
                    ),
                )
            )

    if not nct_ids:
        if _COUNT_PREFIX.search(sentence) or _COUNT_NOUN.search(sentence):
            _check_counts(findings, field, sentence, context)
        if _PERCENT.search(sentence) and not cited and not _UNCHECKED_NUMBER.search(sentence):
            findings.append(
                _finding(
                    "NUMERIC_CLAIM_UNSOURCEDED", "error", field, sentence,
                    expected="a quantitative claim that names its supporting record",
                    observed="a figure with no identifier in the sentence",
                    correction=(
                        "Name the source record with its population, dose, endpoint and "
                        "time point, or state the finding without the figure and mark it "
                        "for review."
                    ),
                )
            )
        _check_language(findings, field, sentence, context)
        return

    for match in _NCT.finditer(sentence):
        nct = match.group(0).upper()
        trial = context.trials.get(nct)
        if trial is None:
            # Already reported above as a fabricated identifier.
            continue

        # A list states one phase per study, so the claim tested is the wording in
        # this identifier's own clause, nearest to it — not the sentence opener.
        span = match.span()
        low, high = _clause_bounds(sentence, span[0])
        phase = min(
            _PHASE.finditer(sentence, low, high),
            key=lambda found: _span_gap(span, found.span()),
            default=None,
        )
        if phase and not _phase_agrees(trial, phase.group(0)):
            findings.append(
                _finding(
                    "TRIAL_PHASE_MISMATCH", "error", field, sentence,
                    expected=f"{nct} registry phase: {trial.phase or 'not reported'}",
                    observed=f"the narrative states {phase.group(0).strip()!r} beside it",
                    source_ref=trial.source_url or trial.url,
                    correction=(
                        f"Use the registry value ({trial.phase}) for {nct}, or leave the "
                        "phase out of this sentence."
                    ),
                )
            )

        claimed = _claimed_statuses(sentence)
        if (
            claimed
            and trial.overall_status
            and trial.overall_status.upper() not in claimed
        ):
            findings.append(
                _finding(
                    "TRIAL_STATUS_MISMATCH", "error", field, sentence,
                    expected=f"{nct} registry status: {trial.status}",
                    observed=(
                        "the narrative implies "
                        + " or ".join(dict.fromkeys(_claimed_label(c) for c in claimed))
                    ),
                    source_ref=trial.source_url or trial.url,
                    correction=f"Use the registry status ({trial.status}) for {nct}.",
                )
            )

        parties: list[str] = []
        for group in _INTERACTION_PARTY.findall(sentence):
            for party in _PARTY_SPLIT.split(group):
                party = party.strip()
                # A one-word connector or a bare class noun is not an agent name.
                # A development code ("PF-07081532") is: it carries digits, not
                # four letters.
                if len(party) < 4 or not (
                    re.search(r"[a-z]{4}", party, re.I) or re.search(r"\d{4}", party)
                ):
                    continue
                parties.append(party)
        for party in parties:
            if _registered_intervention(trial, party):
                continue
            listed = ", ".join(trial.interventions or []) or "none listed"
            findings.append(
                _finding(
                    "TRIAL_INTERACTION_UNSUPPORTED", "error", field, sentence,
                    expected=f"{nct} registered interventions: {listed}",
                    observed=(
                        f"an interaction is asserted with {party!r}, which this "
                        "record does not register as an intervention"
                    ),
                    source_ref=trial.source_url or trial.url,
                    correction=(
                        f"Attribute the {party} assessment only to a study drug the "
                        f"registry pairs it with in {nct}, or omit the pairing."
                    ),
                )
            )
        named = [p for p in parties if _registered_intervention(trial, p)]
        if len(named) >= 2 and trial.arm_groups and not _co_administered(trial, named):
            arms = "; ".join(
                f"{group.label or 'arm not named'}: "
                + ", ".join(group.intervention_names or ["no intervention named"])
                for group in trial.arm_groups
            )
            findings.append(
                _finding(
                    "TRIAL_INTERACTION_UNSUPPORTED", "error", field, sentence,
                    expected=f"{nct} registry arms — {arms}",
                    observed=(
                        f"{', '.join(named)} are asserted to have been assessed "
                        "together, but no single arm of this record registers them "
                        "both"
                    ),
                    source_ref=trial.source_url or trial.url,
                    correction=(
                        f"Say which arm of {nct} received each product, or cite a record "
                        "that registers them in one arm."
                    ),
                )
            )

        duration = (
            _DURATION.search(sentence)
            or _DURATION_COMPOUND.search(sentence)
            or _DURATION_BARE.search(sentence)
        )
        if duration:
            problem = _duration_contradiction(trial, duration) or _time_point_contradiction(
                trial, duration
            )
            if problem:
                findings.append(
                    _finding(
                        "TRIAL_DURATION_CONTRADICTS_CLAIM", "error", field, sentence,
                        expected=problem[0],
                        observed=problem[1],
                        source_ref=trial.source_url or trial.url,
                        correction=(
                            "Report the endpoint time point the cited record states. Never "
                            "move a result between durations."
                        ),
                    )
                )

        population = _POPULATION.search(sentence)
        if population and trial.enrollment_count:
            stated = int(population.group(1).replace(",", ""))
            if stated != trial.enrollment_count:
                findings.append(
                    _finding(
                        "TRIAL_POPULATION_MISMATCH", "error", field, sentence,
                        expected=(
                            f"{nct} registry enrollment: {trial.enrollment_count} "
                            f"({trial.enrollment_type or 'type not reported'})"
                        ),
                        observed=f"the narrative states {stated} {population.group(2)}",
                        source_ref=trial.source_url or trial.url,
                        correction=(
                            f"Use the enrollment the registry reports for {nct}, or describe "
                            "the population without a number."
                        ),
                    )
                )

    _check_language(findings, field, sentence, context)


def _claimed_label(code: str) -> str:
    return code.replace("_", " ").capitalize()


def _check_counts(
    findings: list[ValidationFinding],
    field: str,
    sentence: str,
    context: _Context,
) -> None:
    """Reject a record count no derived aggregate in this response supports.

    The allowed values are exactly the numbers the tables are built from, so a
    narrative figure either matches an inspectable list or it is an estimate.
    """
    if not context.allowed_counts:
        return
    stated: list[int] = [int(m.group(1)) for m in _COUNT_PREFIX.finditer(sentence)]
    for match in _COUNT_NOUN.finditer(sentence):
        number = int(match.group(1))
        # "in 2026 12 publications" reads a year, not a record count.
        if 1900 <= number <= 2100:
            continue
        stated.append(number)
    for number in stated:
        if number in context.allowed_counts or number <= 1:
            continue
        findings.append(
            _finding(
                "COUNT_NOT_IN_RETRIEVAL", "error", field, sentence,
                expected=(
                    "one of the counts this dossier computes from retrieved records: "
                    + ", ".join(str(v) for v in sorted(context.allowed_counts))
                ),
                observed=f"the narrative states {number}",
                correction=(
                    "Quote a count printed in the tables with its unit, or state the "
                    "finding without a number."
                ),
            )
        )


_FULL_COVERAGE_CLAIMS = (
    "comprehensive search", "comprehensive review", "exhaustive", "complete set of",
    "all available evidence", "every trial", "all trials on", "full literature",
    "systematically searched all",
)


def _check_language(
    findings: list[ValidationFinding],
    field: str,
    sentence: str,
    context: _Context,
) -> None:
    lowered = sentence.lower()

    if context.partial and any(phrase in lowered for phrase in _FULL_COVERAGE_CLAIMS):
        findings.append(
            _finding(
                "RETRIEVAL_INCOMPLETE", "error", field, sentence,
                expected=(
                    "coverage stated as what this retrieval returned, with the sources "
                    "and date it covered"
                ),
                observed="a partial result set described as comprehensive",
                correction=(
                    "Say which sources were queried and that the result set was capped; "
                    "a capped retrieval cannot be called complete."
                ),
            )
        )

    if any(phrase in lowered for phrase in _ABSENCE_PHRASES):
        findings.append(
            _finding(
                "ABSENCE_OVERCLAIM", "error", field, sentence,
                expected=(
                    "a statement about what this retrieval found, qualified by its "
                    "query terms, sources and retrieval date"
                ),
                observed="a claim that the evidence does not exist",
                correction=(
                    "Reword as \"not resolved by this retrieval\" and list the scope; a "
                    "partial result set cannot establish that a topic is unexplored."
                ),
            )
        )

    if any(phrase in lowered for phrase in _SURROGATE_OUTCOME) and any(
        phrase in lowered for phrase in _CLINICAL_BENEFIT
    ) and not _BENEFIT_DENIAL.search(sentence):
        findings.append(
            _finding(
                "SURROGATE_ENDPOINT_OVERCLAIM", "warning", field, sentence,
                expected=(
                    "a histological, imaging or biomarker reading named as the outcome it "
                    "measured, with the clinical endpoint it does not yet establish stated"
                ),
                observed=(
                    "a surrogate outcome stated alongside clinical-benefit wording in the "
                    "same sentence"
                ),
                correction=(
                    "Keep the two apart: the record reports the surrogate. A hard clinical "
                    "or long-term benefit needs the record that measured it."
                ),
            )
        )

    if any(phrase in lowered for phrase in _PHARMACOVIGILANCE):
        hedged = any(phrase in lowered for phrase in _NON_CAUSAL_HEDGE)
        causal = any(phrase in lowered for phrase in _CAUSAL_OR_INCIDENCE)
        if causal and not hedged:
            findings.append(
                _finding(
                    "REPORTING_SIGNAL_OVERCLAIM", "error", field, sentence,
                    expected=(
                        "a spontaneous-reporting signal described as a signal, with the "
                        "limits of that design stated"
                    ),
                    observed="reporting-signal wording paired with causal or incidence wording",
                    correction=(
                        "State that disproportionate reporting cannot establish "
                        "incidence, causality or comparative risk on its own."
                    ),
                )
            )
        elif not hedged:
            findings.append(
                _finding(
                    "REPORTING_SIGNAL_OVERCLAIM", "warning", field, sentence,
                    expected="the limits of spontaneous-reporting data stated next to the signal",
                    observed="no non-causal qualifier in the sentence",
                    correction="Add that these reports cannot establish incidence or causality.",
                )
            )

    if any(phrase in lowered for phrase in _LABEL_CLAIM):
        names_product = (
            any(product in lowered for product in context.products)
            or bool(re.search(r"\b(?:NDA|ANDA|BLA)\s*\d{4,6}\b", lowered, re.I))
        )
        if not names_product:
            findings.append(
                _finding(
                    "LABEL_CLAIM_WITHOUT_PRODUCT", "error", field, sentence,
                    expected=(
                        "a labelling claim attributed to the specific product and "
                        "application number it comes from"
                    ),
                    observed=(
                        "a labelling statement naming no product; separately approved "
                        "products of the same molecule do not share indications"
                    ),
                    correction=(
                        "Name the product and its application number, or move the "
                        "sentence into the per-product label table."
                    ),
                )
            )

    if any(phrase in lowered for phrase in _NON_HUMAN) and not any(
        phrase in lowered for phrase in _HUMAN_DOUBT
    ):
        findings.append(
            _finding(
                "PRECLINICAL_HUMAN_RELEVANCE", "warning", field, sentence,
                expected="a preclinical finding reported as preclinical",
                observed="preclinical wording without the source's own human-relevance caveat",
                correction=(
                    "State that the relevance of this finding to people is what the "
                    "source says it is, and cite the record."
                ),
            )
        )


def _check_arithmetic(
    findings: list[ValidationFinding], context: _Context
) -> None:
    strength = context.strength
    if strength:
        total = sum(category.count for category in strength.categories)
        if not strength.reconciles or total != strength.total_records:
            findings.append(
                _finding(
                    "ARITHMETIC_UNRECONCILED", "error", "evidence_strength", strength.denominator,
                    expected=f"{strength.total_records} evidence records",
                    observed=f"the class counts sum to {total}",
                    correction="Give each record exactly one class, then recompute the table.",
                )
            )
        if strength.publication_records + strength.regulatory_passages != strength.total_records:
            findings.append(
                _finding(
                    "ARITHMETIC_UNRECONCILED", "error", "evidence_strength", strength.denominator,
                    expected=f"{strength.total_records} evidence records",
                    observed=(
                        f"{strength.publication_records} publications + "
                        f"{strength.regulatory_passages} label passages"
                    ),
                    correction="Split the evidence set by unit before publishing the totals.",
                )
            )
        if strength.unclassified_count:
            findings.append(
                _finding(
                    "DESIGN_UNSPECIFIED", "warning", "evidence_strength", strength.denominator,
                    expected="a publication type that names a study design",
                    observed=(
                        f"{strength.unclassified_count} record(s) carry no recognised "
                        "publication type"
                    ),
                    correction=(
                        "List them as unclassified; do not count them toward a design "
                        "or evidence class."
                    ),
                )
            )

    analytics = context.analytics
    if analytics:
        if not analytics.statuses_reconcile:
            findings.append(
                _finding(
                    "ARITHMETIC_UNRECONCILED", "error", "trial_analytics.trials_by_status",
                    analytics.ongoing_definition,
                    expected=f"{analytics.total_trials} distinct trials",
                    observed=f"the status rows sum to {analytics.exclusive_status_total}",
                    correction="Route every record into exactly one status category.",
                )
            )
        phase_total = sum(bucket.count for bucket in analytics.trials_by_phase)
        if phase_total != analytics.total_trials:
            findings.append(
                _finding(
                    "ARITHMETIC_UNRECONCILED", "error", "trial_analytics.trials_by_phase", "",
                    expected=f"{analytics.total_trials} distinct trials",
                    observed=f"the phase rows sum to {phase_total}",
                    correction="Chart one bucket per distinct trial.",
                )
            )

    attribution = context.attribution
    if attribution and attribution.applicable:
        parts = sum(category.count for category in attribution.categories)
        if parts != attribution.distinct_trials:
            findings.append(
                _finding(
                    "ARITHMETIC_UNRECONCILED", "error", "query_attribution",
                    attribution.reconciliation_note,
                    expected=f"{attribution.distinct_trials} distinct trials",
                    observed=f"the attribution categories sum to {parts}",
                    correction="Attribute each trial once, from its registered interventions.",
                )
            )


def _check_retrieval(
    findings: list[ValidationFinding],
    sources: list[SourceStatus],
    partial_retrieval: bool,
    trials: list[ClinicalTrial],
) -> None:
    for source in sources:
        if source.status == "error":
            findings.append(
                _finding(
                    "SOURCE_NOT_CONSULTED", "warning", "sources_status",
                    f"{source.source_name}: {source.error_message or 'could not be consulted'}",
                    expected="the source to answer, or the affected section to read as unverified",
                    observed=f"{source.source_name} failed",
                    correction="Re-query it, or state that its absence is not evidence of absence.",
                )
            )
        elif source.status == "no_results":
            findings.append(
                _finding(
                    "SOURCE_NOT_CONSULTED", "warning", "sources_status",
                    f"{source.source_name}: zero records returned",
                    expected="zero records read as \"nothing returned for these terms\"",
                    observed="an empty result set",
                    correction="Keep the wording away from \"no evidence exists\".",
                )
            )
    if partial_retrieval:
        findings.append(
            _finding(
                "RETRIEVAL_INCOMPLETE", "warning", "sources", "",
                expected="a complete result set",
                observed="at least one source capped or cut its results",
                correction="Keep the partial-retrieval label and do not claim full coverage.",
            )
        )
    missing = [trial.nct_id for trial in trials if not (trial.source_url and trial.retrieved_at)]
    if missing:
        findings.append(
            _finding(
                "RECORD_PROVENANCE_MISSING", "warning", "clinical_trials",
                ", ".join(missing[:8]),
                expected="a source URL and retrieval timestamp on every record",
                observed=f"{len(missing)} record(s) without them",
                correction="Re-verify these records against the registry before publishing them.",
            )
        )


def collect_identifiers(evidence: Iterable[EvidenceItem]) -> list[str]:
    """Every identifier a retrieved record carries, in the forms prose may use.

    A narrative citation is only checkable against the spelling the record itself
    reports, so PMID, DOI, PMCID, CID and the bare id are all included.
    """
    out: list[str] = []
    for item in evidence:
        meta = item.metadata or {}
        for key in ("pmid", "doi", "pmcid", "cid", "application_number"):
            value = meta.get(key) or (item.id if key == "application_number" else None)
            if not value:
                continue
            text = str(value).strip()
            if not text:
                continue
            prefix = {"pmid": "PMID:", "doi": "DOI:", "pmcid": "PMC", "cid": "CID:"}.get(key)
            out.append(f"{prefix}{text}" if prefix else text)
            out.append(text)
        if item.id:
            out.append(str(item.id))
    return out


def collect_label_products(evidence: Iterable[EvidenceItem]) -> list[str]:
    """Product names an retrieved openFDA label actually covers.

    Used to reject a labelling sentence about a brand no label in this response
    describes — the same molecule can be approved under separate applications
    with different indications and warnings.
    """
    names: list[str] = []
    for item in evidence:
        meta = item.metadata or {}
        for key in ("generic_names", "brand_names"):
            for name in meta.get(key) or []:
                text = str(name).strip()
                if text:
                    names.append(text.lower())
    return names


def validate_dossier(
    dossier: Optional[Dossier],
    trials: list[ClinicalTrial],
    identifiers: Iterable[str] = (),
    label_products: Iterable[str] = (),
    evidence_strength: Optional[EvidenceStrength] = None,
    analytics: Optional[TrialAnalytics] = None,
    attribution: Optional[QueryAttributionSummary] = None,
    sources: Optional[list[SourceStatus]] = None,
    partial_retrieval: bool = False,
) -> ValidationReport:
    """Run every rule against the finished dossier and return the QA report."""
    context = _Context(
        trials, identifiers, label_products, analytics, evidence_strength,
        attribution, partial_retrieval,
    )
    findings: list[ValidationFinding] = []
    for field, text in _narrative_fields(dossier):
        for sentence in _sentences(text):
            _check_sentence(findings, field, sentence, context)
    _check_arithmetic(findings, context)
    _check_retrieval(findings, sources or [], partial_retrieval, trials)

    # One objection, stated once. A report that repeats a row the reader has
    # already seen reads as a longer list of problems than there are.
    unique: list[ValidationFinding] = []
    seen: set[tuple] = set()
    for item in findings:
        key = (item.rule, item.field, item.quote, item.expected, item.observed)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    return ValidationReport(
        errors=sum(1 for item in unique if item.severity == "error"),
        warnings=sum(1 for item in unique if item.severity == "warning"),
        blocked=any(item.blocks_publication for item in unique),
        findings=unique,
        rules_run=list(RULES),
        checked_fields=[field for field, _ in _narrative_fields(dossier)],
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
