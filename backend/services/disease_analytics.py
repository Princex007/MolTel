"""Disease-area view of the retrieved records (spec §6.2, §6.3).

Two sources of wording are kept apart on purpose: what a standardized disease
ontology calls a concept, and what the registry records themselves say in their
condition field. A subtype is listed when one of those two sources uses the
wording; a record is attached to it only when the record carries that wording
itself. Nothing here claims a validated disease classification, and a subtype
with no records describes this retrieved set rather than the state of research.

Condition wording is compared as a set of words, with the distinctions a reader
would expect: a word introduced by "non-" or "no-" is denied rather than used, so
"small cell lung cancer" is not filed under "non-small cell lung cancer", and an
abbreviation bracketed beside the words it stands for names the same thing, so
either may be the wording a record carries.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Optional

from models.schemas import (
    CandidateAnalytics,
    ChartBucket,
    ClinicalTrial,
    DiseaseAnalytics,
    DiseaseConcept,
    DiseaseSubtype,
    DiseaseTerm,
    EvidenceItem,
    TargetProfile,
    TrialRetrievalMetadata,
)

# A subtype list long enough to scroll past the dashboard stops being useful.
# What is left out is counted and reported, never silently dropped.
MAX_SUBTYPES_WITH_RECORDS = 40
MAX_EMPTY_SUBTYPES = 15

_NO_RECORDS_NOTE = (
    "No trial in this retrieved set uses this wording. It says what was fetched "
    "for this query, not that research on this subtype is missing."
)

# A word that reverses the meaning of the word after it. "Non-small cell lung
# cancer" does not describe small cell lung cancer, so a word one label denies
# cannot be satisfied by another label that uses it.
NEGATION_MARKERS = frozenset({"non", "no", "without", "seronegative"})

# Words that carry no disease meaning of their own, so they are not required of
# a record. Without this, "carcinoma of the lung" and "lung carcinoma" would be
# two different subtypes.
STOP_WORDS = frozenset(
    {
        "a", "an", "and", "of", "the", "in", "for", "to", "on", "at",
        "by", "with", "or", "is", "as", "from",
    }
)

# A one-word subtype wording matches almost any record, so only a word that is
# not part of the queried disease's own wording — an abbreviation or a name —
# is allowed to stand on its own.
MIN_WORDING_WORDS = 2


def normalize_label(text: str) -> str:
    """Display-independent match key: whitespace collapsed, case folded."""
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _stem(word: str) -> str:
    # Singular and plural are folded: "lung neoplasms" names "lung neoplasm".
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def _words(text: str) -> list[str]:
    return [_stem(t) for t in re.split(r"[^a-z0-9]+", normalize_label(text)) if t]


@dataclass(frozen=True)
class Wording:
    """One name for a condition: the words it uses and the words it denies."""

    affirmed: frozenset
    denied: frozenset

    @property
    def key(self) -> str:
        return " ".join(sorted(self.affirmed)) + "|" + " ".join(sorted(self.denied))


def _parse(words: Iterable[str]) -> Wording:
    affirmed: set[str] = set()
    denied: set[str] = set()
    negate = False
    for word in words:
        if word in NEGATION_MARKERS:
            negate = True
            continue
        if negate:
            denied.add(word)
            negate = False
            continue
        if word not in STOP_WORDS:
            affirmed.add(word)
    return Wording(frozenset(affirmed), frozenset(denied))


def _wordings(text: str) -> list[Wording]:
    """Every way one string names its condition.

    A registry string commonly carries the abbreviation it stands for beside the
    words, as in "Non-small Cell Lung Cancer (NSCLC)". Either name may be the one
    another record uses, so both are offered — as alternatives, never combined,
    so a record still has to carry a complete name rather than words picked from
    two of them.
    """
    raw = _clean(text)
    groups = re.findall(r"[([{]([^)\]}]*)[)\]}]", raw)
    out: list[Wording] = []

    def add(words: list[str]) -> None:
        wording = _parse(words)
        if wording.affirmed and all(wording.key != existing.key for existing in out):
            out.append(wording)

    add(_words(re.sub(r"[([{][^)\]}]*[)\]]", " ", raw)))
    for group in groups:
        add(_words(group))
    return out


def _carries(field_wording: Wording, wanted: Wording) -> bool:
    """Whether record wording carries a term's name.

    Every word the term uses must be used by the record, and a word either side
    denies must not be the other side's to use.
    """
    if not wanted.affirmed or not wanted.affirmed <= field_wording.affirmed:
        return False
    return not (wanted.denied & field_wording.affirmed) and not (
        field_wording.denied & wanted.affirmed
    )


def _narrows(child: Wording, parent: Wording) -> bool:
    """Whether one name states everything the other names, and more."""
    return _carries(child, parent)


# Words an ontology uses to say what kind of record a name is, rather than to
# name the condition: MONDO writes "meningioma (disease) of lung". On its own
# such a word matches every record that mentions a disease, so it is never
# offered as a name. An abbreviation like "NSCLC" is one word and does name the
# condition, so it is kept.
QUALIFIER_WORDS = frozenset(
    {
        "disease", "disorder", "condition", "syndrome", "manifestation",
        "symptom", "sign", "finding", "abnormality", "complaint", "entity",
    }
)


def _usable(wording: Wording, broad_words: frozenset) -> bool:
    """Whether a wording is specific enough to identify records with."""
    if not wording.affirmed:
        return False
    if len(wording.affirmed) >= MIN_WORDING_WORDS:
        return True
    if wording.affirmed & QUALIFIER_WORDS:
        return False
    return not (wording.affirmed & broad_words)


def _carries_any(field_wordings: list[Wording], wanted: list[Wording]) -> bool:
    return any(_carries(pair, need) for pair in field_wordings for need in wanted)


def paper_names_label(item: EvidenceItem, label: str) -> bool:
    """Whether a paper's own title or abstract carries this label's wording.

    Exposed for the literature subtype filter so it uses this same word rule
    rather than a second, looser one.
    """
    wanted = _wordings(label)
    if not wanted:
        return False
    return _carries_any(_wordings_of(_paper_fields(item)), wanted)


def _trial_fields(trial: ClinicalTrial) -> list[str]:
    """The registry wording a subtype may be matched against for this trial.

    Only the condition list and the brief title: both are the registry's own
    wording for what the study is about. A summary that merely mentions a term
    is not treated as naming that condition.
    """
    return [*(trial.conditions or []), trial.title or ""]


def _paper_fields(item: EvidenceItem) -> list[str]:
    return [item.title or "", item.abstract or ""]


def _target_fields(target: TargetProfile) -> list[str]:
    return [target.name or "", target.gene or "", target.function_summary or ""]


def _wordings_of(fields: Iterable[str]) -> list[Wording]:
    out: list[Wording] = []
    for text in fields:
        for wording in _wordings(text):
            if all(wording.key != existing.key for existing in out):
                out.append(wording)
    return out


@dataclass
class _Entry:
    """A subtype candidate and every wording that has been seen naming it."""

    label: str
    term: Optional[DiseaseTerm]
    origin: str
    own: Wording
    wordings: list[Wording] = field(default_factory=list)
    parent: Optional[str] = None
    parent_concept_id: Optional[str] = None
    refines: Optional[str] = None
    refines_source: Optional[str] = None
    level: int = 0


def _canonical_wordings(concept: Optional[DiseaseConcept], query: str) -> list[Wording]:
    """The names that mean the queried disease itself.

    A registry string equal to one of these is the condition being searched, or
    one of the concept's own recorded synonyms, so it is not a subtype of it.

    These names are also the anchors a candidate must narrow to be offered as a
    subtype, so a wording that names nothing — the "(disease)" MONDO brackets into
    "lung carcinoma (disease)" — is left out here: as an anchor it would admit
    every condition string that mentions a disease.
    """
    out: list[Wording] = []
    canonical = concept.canonical if concept is not None else None
    own_words = frozenset(_words(canonical.label)) if canonical is not None else frozenset()
    texts: list[tuple[str, bool]] = [(query, True)] if query else []
    if canonical is not None:
        texts.append((canonical.label, True))
        texts.extend((synonym, False) for synonym in canonical.synonyms)
    for text, is_name_of_the_query in texts:
        for wording in _wordings(text):
            if not wording.affirmed or wording.affirmed <= QUALIFIER_WORDS:
                continue
            if not is_name_of_the_query and not _usable(wording, own_words):
                continue
            if all(wording.key != existing.key for existing in out):
                out.append(wording)
    return out


def _concept_wordings(term: DiseaseTerm, broad_words: frozenset) -> list[Wording]:
    """A concept's own name plus the synonyms the ontology records for it."""
    out: list[Wording] = []
    for text in (term.label, *term.synonyms):
        for wording in _wordings(text):
            if not _usable(wording, broad_words):
                continue
            if all(wording.key != existing.key for existing in out):
                out.append(wording)
    return out


def _merge_pool(
    concept: Optional[DiseaseConcept],
    registry_labels: Counter,
    canonical: list[Wording],
) -> tuple[dict[str, _Entry], int]:
    """Build the subtype pool from both wording sources, keyed by name.

    A standardized concept is listed only where the ontology states the relation:
    a concept it files as a child of the matched term. What its search returned
    for overlapping wording is not offered as a subtype, because overlap cannot be
    read as direction — searching lung cancer returns "carcinoma", which names
    carcinomas of every organ, and filing it as a subtype would count breast and
    renal studies under a lung query, then reuse its wording as a name to match
    records against. A registry condition string is listed when it names the
    queried disease using every word of one of its names plus something more
    specific; a string that only repeats part of the name — "Cancer" under a
    search for "lung cancer" — is broader than the query, so it is reported as
    other condition wording instead of as a subtype. A string carrying a name the
    ontology already recorded for a listed concept is filed under that concept
    rather than beside it.

    Returns the pool and how many returned concepts stated no subtype relation.
    """
    entries: dict[str, _Entry] = {}
    aliases: dict[str, _Entry] = {}
    named = {wording.key for wording in canonical}
    broad_words = frozenset(set().union(*(set(w.affirmed) for w in canonical))) if canonical else frozenset()
    anchors = list(canonical)
    unstated_concepts = 0

    def register(entry: _Entry) -> None:
        entries.setdefault(entry.own.key, entry)
        for wording in entry.wordings:
            aliases.setdefault(wording.key, entry)

    if concept is not None:
        for term in concept.related:
            own = _wordings(term.label)
            if not own or own[0].key in named:
                continue
            wordings = _concept_wordings(term, broad_words) or own
            if term.parent is None:
                # A concept the ontology's search returned for wording overlap,
                # which states no relation to the matched term.
                unstated_concepts += 1
                continue
            register(
                _Entry(
                    label=term.label,
                    term=term,
                    origin="standardized concept",
                    own=own[0],
                    wordings=list(wordings),
                    parent=term.parent,
                    parent_concept_id=term.parent_concept_id,
                )
            )
            # A concept the ontology files as a child joins the names registry
            # strings are matched against, so a string spelling one of its
            # recorded synonyms is filed under it rather than beside it.
            anchors.extend(wordings)

    for label in registry_labels:
        wordings = _wordings(label)
        if not wordings:
            continue
        if any(wording.key in named for wording in wordings):
            continue
        matched = next((aliases[w.key] for w in wordings if w.key in aliases), None)
        if matched is not None:
            if matched.term is not None:
                matched.origin = "both"
            for wording in wordings:
                if all(wording.key != existing.key for existing in matched.wordings):
                    matched.wordings.append(wording)
            register(matched)
            continue
        usable = [w for w in wordings if _usable(w, broad_words)]
        if not any(
            _narrows(wording, anchor) for wording in usable for anchor in anchors
        ):
            continue
        register(
            _Entry(
                label=label,
                term=None,
                origin="registry condition wording",
                own=usable[0],
                wordings=usable,
            )
        )
    return entries, unstated_concepts


def _nest(entries: list[_Entry], root_label: str, root_wordings: list[Wording]) -> None:
    """File each subtype under the term it refines.

    Where the ontology states that relation, it is used as published. Otherwise
    the relation follows the wording: a name is filed under the closest listed
    name whose words it uses in full, and a name formed by denying part of
    another name is never filed under the wording it denies.
    """
    by_label = {normalize_label(entry.label): entry for entry in entries}
    root = normalize_label(root_label)

    for entry in entries:
        parent = normalize_label(entry.parent or "")
        if parent and parent != normalize_label(entry.label):
            if parent == root:
                entry.refines, entry.refines_source = root_label, "standardized hierarchy"
                continue
            listed = by_label.get(parent)
            if listed is not None:
                entry.refines, entry.refines_source = listed.label, "standardized hierarchy"
                continue
        best: Optional[_Entry] = None
        for other in entries:
            if other is entry or not _narrows(entry.own, other.own):
                continue
            if best is None or len(other.own.affirmed) > len(best.own.affirmed):
                best = other
        if best is not None:
            entry.refines, entry.refines_source = best.label, "wording containment"
        elif any(_narrows(entry.own, wording) for wording in root_wordings):
            entry.refines, entry.refines_source = root_label, "wording containment"

    for entry in entries:
        depth, seen = 0, {normalize_label(entry.label)}
        parent = entry.refines
        while parent is not None:
            key = normalize_label(parent)
            depth += 1
            if key == root or key in seen:
                break
            seen.add(key)
            listed = by_label.get(key)
            if listed is None:
                break
            parent = listed.refines
        entry.level = depth


def _canonical_display(
    query: str,
    concept: Optional[DiseaseConcept],
    condition_counts: Counter,
    trials: list[ClinicalTrial],
) -> tuple[str, str, Optional[DiseaseTerm]]:
    """The term shown as canonical, and where that term came from."""
    canonical = concept.canonical if concept is not None else None
    if canonical is not None:
        identifiers = " ".join(x for x in (canonical.ontology, canonical.concept_id) if x)
        provenance = (
            f'Search "{query}" matched the standardized disease concept '
            f'"{canonical.label}"'
            + (f" ({identifiers})" if identifiers else "")
            + (f", recorded at {canonical.url}" if canonical.url else "")
            + ". The query is kept exactly as submitted."
        )
        return canonical.label, provenance, canonical
    if condition_counts:
        # Prefer a string that shares wording with the query, then the most
        # frequent one: a registry's conditions list is not a controlled
        # vocabulary, so this is the closest thing to a term the records offer.
        query_word_tokens = frozenset(_words(query))
        top_label, top_count = max(
            condition_counts.items(),
            key=lambda item: (len(frozenset(_words(item[0])) & query_word_tokens), item[1]),
        )
        provenance = (
            "No standardized concept matched this query, so the most frequent "
            f'condition string naming it is shown instead ("{top_label}", used by '
            f"{top_count} of {len(trials)} trials). That is registry wording, not a "
            "canonical disease term."
        )
        return top_label, provenance, None
    provenance = (
        "Neither the disease ontology nor the retrieved records supplied a "
        "term for this query, so it is shown exactly as submitted."
    )
    return query, provenance, None


def _limitations(
    concept: Optional[DiseaseConcept],
    metadata: Optional[TrialRetrievalMetadata],
    omitted: int,
    trials: int,
    unstated_concepts: int = 0,
) -> list[str]:
    limitations: list[str] = []
    if concept is None or not concept.source_reached:
        limitations.append(
            "The disease ontology could not be consulted, so no standardized term "
            "or synonym set is available for this query."
        )
    elif concept.canonical is None:
        limitations.append(
            "The disease ontology returned no concept sharing wording with this "
            "query, so no canonical term is asserted."
        )
    elif concept.canonical is not None and not concept.hierarchy_reached:
        limitations.append(
            "The ontology's child concepts of this term could not be read, so no "
            "standardized subtype is available for it; the subtype list below uses "
            "only the condition wording the retrieved records use."
        )
    if metadata is not None and not metadata.source_reached:
        limitations.append(
            "ClinicalTrials.gov could not be consulted, so the subtype lists below "
            "carry trial records only where another source supplied them."
        )
    elif metadata is not None and metadata.partial:
        limitations.append(
            f"Subtype counts cover the {metadata.records_returned} trial records "
            "retrieved for this query, not every registered study of it."
        )
    if omitted:
        limitations.append(
            f"{omitted} further subtype candidate(s) were left off the list for "
            "length; the ones shown are those naming the most retrieved trials."
        )
    if concept is not None and concept.excluded_related:
        limitations.append(
            f"{concept.excluded_related} concept(s) the ontology returned were left "
            "out because their wording does not overlap this query, or because they "
            "name a genetic linkage locus rather than a subtype."
        )
    if unstated_concepts:
        limitations.append(
            f"{unstated_concepts} concept(s) the ontology's search returned for "
            "wording overlapping this query state no relation to the matched term, "
            "so they are not listed as its subtypes: only the concepts the ontology "
            "itself files as children of that term are."
        )
    if concept is not None and concept.note:
        limitations.append(concept.note)
    return limitations


def compute_disease_analytics(
    query: str,
    concept: Optional[DiseaseConcept],
    trials: list[ClinicalTrial],
    evidence: list[EvidenceItem],
    candidates: Optional[CandidateAnalytics],
    targets: list[TargetProfile],
    metadata: Optional[TrialRetrievalMetadata] = None,
) -> DiseaseAnalytics:
    """Build the disease dashboard view from records already retrieved."""

    condition_counts: Counter[str] = Counter()
    for trial in trials:
        for label in trial.conditions or []:
            text = _clean(label)
            if text:
                condition_counts[text] += 1

    canonical = _canonical_wordings(concept, query)
    pool, unstated_concepts = _merge_pool(concept, condition_counts, canonical)

    papers = [item for item in evidence if item.source_type == "literature"]
    candidate_records = list(candidates.records) if candidates else []
    trial_by_id = {trial.nct_id: trial for trial in trials}

    # Each record's wording is read once, then compared against every subtype.
    trial_wordings = {trial.nct_id: _wordings_of(_trial_fields(trial)) for trial in trials}
    condition_wordings = {text: _wordings_of([text]) for text in condition_counts}
    paper_wordings = [(item, _wordings_of(_paper_fields(item))) for item in papers]
    target_wordings = [(item, _wordings_of(_target_fields(item))) for item in targets]

    entries_by_label = {normalize_label(entry.label): entry for entry in pool.values()}
    subtypes: list[DiseaseSubtype] = []
    for entry in pool.values():
        wanted = entry.wordings
        subtype = DiseaseSubtype(
            label=entry.label, origin=entry.origin, concept=entry.term, availability_note=""
        )
        nct_ids: list[str] = []
        for trial in trials:
            if not _carries_any(trial_wordings[trial.nct_id], wanted):
                continue
            nct_ids.append(trial.nct_id)
            for text in trial.conditions or []:
                clean = _clean(text)
                if clean and _carries_any(condition_wordings.get(clean, []), wanted):
                    subtype.condition_labels.append(clean)
        subtype.trial_nct_ids = sorted(set(nct_ids))
        subtype.condition_labels = sorted(set(subtype.condition_labels))

        attached = [trial_by_id[n] for n in subtype.trial_nct_ids if n in trial_by_id]
        subtype.company_names = sorted(
            {t.sponsor.strip() for t in attached if t.sponsor and t.sponsor.strip()}
        )
        subtype.candidate_names = sorted(
            {
                record.name
                for record in candidate_records
                if set(record.nct_ids) & set(subtype.trial_nct_ids)
            }
        )
        subtype.paper_keys = sorted(
            {
                f"{item.source}:{item.id or item.url or ''}"
                for item, wordings in paper_wordings
                if _carries_any(wordings, wanted)
            }
        )
        subtype.target_accessions = sorted(
            {
                item.accession
                for item, wordings in target_wordings
                if _carries_any(wordings, wanted)
            }
        )
        if not subtype.trial_nct_ids:
            subtype.availability_note = _NO_RECORDS_NOTE
        subtypes.append(subtype)

    with_records = sorted(
        (s for s in subtypes if s.trial_nct_ids),
        key=lambda s: (-len(s.trial_nct_ids), normalize_label(s.label)),
    )
    without_records = sorted(
        (s for s in subtypes if not s.trial_nct_ids),
        key=lambda s: normalize_label(s.label),
    )
    shown = with_records[:MAX_SUBTYPES_WITH_RECORDS]
    shown += without_records[:MAX_EMPTY_SUBTYPES]
    omitted = (len(with_records) - len(with_records[:MAX_SUBTYPES_WITH_RECORDS])) + (
        len(without_records) - len(without_records[:MAX_EMPTY_SUBTYPES])
    )

    canonical_term, provenance, concept_term = _canonical_display(
        query, concept, condition_counts, trials
    )
    shown_entries = [entries_by_label[normalize_label(s.label)] for s in shown]
    _nest(shown_entries, canonical_term, canonical)
    for subtype, entry in zip(shown, shown_entries):
        subtype.refines = entry.refines
        subtype.refines_source = entry.refines_source
        subtype.level = entry.level
    # Records first, then the refinement chain: an ontology subtype no retrieved
    # trial names must not push the populated ones off the top of the list.
    shown.sort(
        key=lambda s: (
            0 if s.trial_nct_ids else 1,
            s.level,
            -len(s.trial_nct_ids),
            normalize_label(s.label),
        )
    )

    # Condition strings no subtype — listed or capped — covers, plus the words of
    # the query itself. A subtype list limited for length must not make the
    # records under the dropped entries vanish from the counts.
    covered: list[Wording] = list(canonical)
    covered.extend(wording for entry in pool.values() for wording in entry.wordings)
    residual: Counter[str] = Counter()
    for trial in trials:
        for text in trial.conditions or []:
            clean = _clean(text)
            if not clean:
                continue
            if _carries_any(condition_wordings.get(clean, []), covered):
                continue
            residual[clean] += 1

    synonyms = list(concept_term.synonyms) if concept_term is not None else []
    trials_without_label = sum(
        1 for trial in trials if not any(str(c).strip() for c in trial.conditions or [])
    )

    return DiseaseAnalytics(
        query=query,
        canonical_term=canonical_term,
        canonical_term_provenance=provenance,
        concept=concept_term,
        synonyms=synonyms,
        subtypes=shown,
        unmatched_condition_labels=[
            ChartBucket(label=label, count=count) for label, count in residual.most_common(20)
        ],
        trials_considered=len(trials),
        trials_with_condition_label=len(trials) - trials_without_label,
        trials_without_condition_label=trials_without_label,
        papers_considered=len(papers),
        targets_considered=len(targets),
        candidates_considered=len(candidate_records),
        subtypes_with_records=sum(1 for s in shown if s.trial_nct_ids),
        subtypes_without_records=sum(1 for s in shown if not s.trial_nct_ids),
        subtypes_omitted=omitted,
        ontology_reached=bool(concept and concept.source_reached),
        limitations=_limitations(concept, metadata, omitted, len(trials), unstated_concepts),
        metadata=metadata,
    )
