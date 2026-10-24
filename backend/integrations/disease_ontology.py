"""Standardized disease concept lookup (spec §6.2).

OLS4 serves the OBO Foundry ontologies. MONDO merges the disease ontologies into
one identifier space, so a single query returns a canonical concept, the names
that concept is also recorded under, and the narrower concepts filed beside it.

The lookup is optional by design. When it fails — or when it finds no concept
that shares wording with the query — the disease dashboard falls back to the
condition strings the retrieved registry records use, and says so, rather than
inventing a canonical term.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from models.schemas import DiseaseConcept, DiseaseTerm
from utils.http import safe_get
from utils.text import condense

logger = logging.getLogger(__name__)

OLS_SEARCH_URL = "https://www.ebi.ac.uk/ols4/api/search"
OLS_CHILDREN_URL = "https://www.ebi.ac.uk/ols4/api/ontologies/mondo/children"
TERM_PAGE_URL = "https://www.ebi.ac.uk/ols4/ontologies/{ontology}/terms?obo_id={obo_id}"
ONTOLOGY = "mondo"
ROWS = 40
CHILD_ROWS = 60
# How many of the matched term's children are opened one level further. A common
# term can have hundreds; the cap bounds the calls, and what was not read is
# reported on the result instead of being passed off as the whole hierarchy.
MAX_CHILD_LOOKUPS = 12
SELECT_FIELDS = "label,obo_id,iri,ontology_name,description,exact_synonyms"

# MONDO files genetic-association phrasings among a disease concept's exact
# synonyms ("lung cancer, susceptibility to, autosomal dominant, somatic
# mutation"). Those name a study of the disease, not the disease, so they are not
# shown as synonyms. How many were left out is reported on the concept.
ASSOCIATION_SYNONYM = re.compile(
    r"(susceptibilit|resistance|response to|association with|somatic|autosomal|germline)",
    re.I,
)
MAX_SYNONYM_CHARS = 64

# A MONDO label that only adds a genetics word or a number to its parent names a
# linkage locus or a susceptibility category, not a clinical subtype of it.
GENETICS_SUFFIX = re.compile(r"\d{1,3}")
GENETICS_WORDS = frozenset(
    {
        "susceptibility",
        "resistance",
        "modifier",
        "locus",
        "loci",
        "predisposition",
        "linked",
        "autosomal",
        "dominant",
        "recessive",
    }
)


def normalize_term(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def term_tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", normalize_term(text)) if t}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _term(doc: dict[str, Any]) -> Optional[DiseaseTerm]:
    label = str(doc.get("label") or "").strip()
    if not label:
        return None
    concept_id = str(doc.get("obo_id") or "").strip() or None
    ontology = str(doc.get("ontology_name") or "").strip() or ONTOLOGY
    descriptions = doc.get("description") or []
    definition = None
    if descriptions:
        text = str(descriptions[0] if isinstance(descriptions, list) else descriptions)
        definition = condense(text, 400) or None
    # The search endpoint reports exact synonyms; the hierarchy endpoints merge
    # every synonym type into one list, which the same filters then narrow.
    raw = doc.get("exact_synonyms") or doc.get("synonyms") or []
    synonyms, excluded = _clean_synonyms(raw, label)
    url = None
    if concept_id:
        url = TERM_PAGE_URL.format(
            ontology=ontology, obo_id=concept_id.replace(":", "%3A")
        )
    return DiseaseTerm(
        label=label,
        concept_id=concept_id,
        ontology=ontology,
        url=url,
        iri=str(doc.get("iri") or "").strip() or None,
        definition=definition,
        synonyms=synonyms,
        excluded_synonyms=excluded,
    )


def _clean_synonyms(raw: list[Any], label: str = "") -> tuple[list[str], int]:
    """Split a concept's synonym list into what is shown and what was left out."""
    shown: list[str] = []
    excluded = 0
    seen = {normalize_term(label)}
    for value in raw:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text:
            continue
        if len(text) > MAX_SYNONYM_CHARS or ASSOCIATION_SYNONYM.search(text):
            excluded += 1
            continue
        key = normalize_term(text)
        if key in seen:
            continue
        seen.add(key)
        shown.append(text)
    return shown, excluded


def _is_genetics_variant(label: str, parent: str) -> bool:
    """Whether a concept label only adds a genetics word or a number to its parent.

    "lung cancer susceptibility 1" and "Alzheimer disease 3" name a linkage locus
    or a susceptibility category rather than a clinical subtype, so they are not
    offered as one. How many such concepts were left out is reported on the lookup.
    """
    mine, theirs = term_tokens(label), term_tokens(parent)
    extra = mine - theirs
    if not extra or not theirs < mine:
        return False
    return all(word in GENETICS_WORDS or word.isdigit() for word in extra)


def _phrases(doc: dict[str, Any]) -> list[str]:
    """The label plus every name the ontology records for this same concept.

    A query is often a name the concept carries rather than its label — "NSCLC"
    is a recorded synonym of "non-small cell lung carcinoma", "malignant neoplasm
    of lung" of "lung cancer" — so matching only labels maps such a query to the
    wrong, merely word-similar, concept.
    """
    return [str(doc.get("label") or "")] + [
        str(s or "") for s in (doc.get("exact_synonyms") or [])
    ]


def _doc_words(doc: dict[str, Any]) -> set[str]:
    words: set[str] = set()
    for phrase in _phrases(doc):
        words |= term_tokens(phrase)
    return words


def _rank(docs: list[dict[str, Any]], query: str) -> list[tuple[int, dict[str, Any]]]:
    """Order returned concepts by how well their wording matches the query.

    The concept whose own label is the query comes first, then one that records
    the query as one of its names, then one whose label or recorded name carries
    every word of the query, then whatever the ontology ranked highest. Distance
    is measured against the label only, so a concept with a long synonym list
    cannot beat one whose name is simply closer to the query.
    """
    q_norm = normalize_term(query)
    q_tokens = term_tokens(query)
    ranked: list[tuple[tuple[int, int, int, int, int], int, dict[str, Any]]] = []
    for index, doc in enumerate(docs):
        phrases = _phrases(doc)
        label = phrases[0]
        label_tokens = term_tokens(label)
        phrase_tokens = [term_tokens(phrase) for phrase in phrases]
        if normalize_term(label) == q_norm:
            exact = 0
        elif any(normalize_term(phrase) == q_norm for phrase in phrases[1:]):
            exact = 1
        else:
            exact = 2
        if q_tokens and q_tokens <= label_tokens:
            covers = 0
        elif q_tokens and any(q_tokens <= tokens for tokens in phrase_tokens[1:]):
            covers = 1
        elif not q_tokens:
            covers = 0
        else:
            covers = 2
        shared = 0 if any(tokens & q_tokens for tokens in phrase_tokens) else 1
        ranked.append(
            (
                (exact, covers, shared, abs(len(label_tokens) - len(q_tokens)), index),
                index,
                doc,
            )
        )
    ranked.sort(key=lambda item: item[0])
    return [(index, doc) for _, index, doc in ranked]


async def _child_docs(iri: str) -> tuple[list[dict[str, Any]], bool]:
    """One level of the ontology's own child concepts, plus whether it was read."""
    data = await safe_get(OLS_CHILDREN_URL, params={"iri": iri, "size": str(CHILD_ROWS)})
    if data is None:
        return [], False
    return ((data.get("_embedded") or {}).get("terms")) or [], True


async def _hierarchy(
    canonical: DiseaseTerm, anchor_words: set[str]
) -> tuple[list[DiseaseTerm], int, bool, int]:
    """Read the canonical concept's children, then their children.

    Two bounded levels are fetched, so the hierarchy shown is the one the source
    publishes rather than one inferred from wording. Nothing deeper is walked:
    how far the list goes is stated on the result, not implied.
    """
    if not canonical.iri:
        return [], 0, False, 0
    first, reached = await _child_docs(canonical.iri)
    if not reached:
        return [], 0, False, 0

    terms: list[DiseaseTerm] = []
    excluded = 0
    expandable = 0
    seen = {normalize_term(canonical.label)}
    next_level: list[tuple[str, DiseaseTerm]] = []
    for doc in first:
        term = _term(doc)
        if term is None or normalize_term(term.label) in seen:
            continue
        if _is_genetics_variant(term.label, canonical.label):
            excluded += 1
            continue
        term.parent, term.parent_concept_id = canonical.label, canonical.concept_id
        seen.add(normalize_term(term.label))
        terms.append(term)
        if doc.get("has_children") and term.iri:
            expandable += 1
            if len(next_level) < MAX_CHILD_LOOKUPS:
                next_level.append((term.iri, term))

    second: list[tuple[DiseaseTerm, list[dict[str, Any]]]] = []
    results = await asyncio.gather(
        *(_child_docs(iri) for iri, _ in next_level), return_exceptions=True
    )
    deeper_failed = False
    for (iri, parent), result in zip(next_level, results):
        if isinstance(result, BaseException):
            deeper_failed = True
            continue
        docs, ok = result
        if not ok:
            deeper_failed = True
            continue
        second.append((parent, docs))

    for parent, docs in second:
        for doc in docs:
            term = _term(doc)
            if term is None or normalize_term(term.label) in seen:
                continue
            if _is_genetics_variant(term.label, parent.label):
                excluded += 1
                continue
            # A deeper concept is kept when its wording still speaks the queried
            # disease; the child list of a common term runs to concepts that have
            # nothing to do with this query. The anchor's own recorded names count
            # as its wording, so a query written as a synonym still keeps them.
            if not (term_tokens(term.label) & anchor_words):
                excluded += 1
                continue
            term.parent, term.parent_concept_id = parent.label, parent.concept_id
            seen.add(normalize_term(term.label))
            terms.append(term)

    # Children that could have been opened further but were not, for length.
    return terms, excluded, not deeper_failed, max(0, expandable - len(next_level))


async def lookup_disease(query: str) -> DiseaseConcept:
    """Look the query up in a standardized disease ontology.

    Always returns a concept record: `source_reached` says whether the ontology
    was consulted at all, and `canonical` is None when no concept shares wording
    with the query. Neither is treated as "the term is not a disease".
    """
    params = {
        "q": query,
        "ontology": ONTOLOGY,
        "rows": str(ROWS),
        "select": SELECT_FIELDS,
    }
    data = await safe_get(OLS_SEARCH_URL, params=params)
    if data is None:
        return DiseaseConcept(
            query=query,
            source_reached=False,
            retrieved_at=_now_iso(),
            note=(
                "The disease ontology could not be reached, so no standardized "
                "term was assigned. Subtype wording below comes from the "
                "condition strings the retrieved records themselves use."
            ),
        )

    docs = ((data.get("response") or {}).get("docs")) or []
    retrieved_at = _now_iso()
    if not docs:
        return DiseaseConcept(
            query=query,
            source_reached=True,
            retrieved_at=retrieved_at,
            note=(
                "The disease ontology returned no concept for this wording. That "
                "describes the ontology, not the condition: the registry may still "
                "record studies for it under its own condition strings."
            ),
        )

    ranked = _rank(docs, query)
    q_tokens = term_tokens(query)
    canonical_index, canonical_doc = ranked[0]
    canonical_term = _term(canonical_doc)
    canonical_words = _doc_words(canonical_doc)
    # The anchor's wording is its label plus the names the ontology records for
    # it, so a query written as one of those names still keeps the hierarchy.
    anchor_words = canonical_words | q_tokens
    if canonical_term is not None and q_tokens and not (canonical_words & q_tokens):
        # Nothing the ontology returned — no label, no recorded name — shares a
        # word with the query. Reporting the top hit as canonical would be a
        # mapping MolTel cannot support.
        canonical_term = None

    # The ontology's own child concepts first: they state the subtype relation,
    # whereas the concepts the search returns only share wording with the query.
    hierarchy: list[DiseaseTerm] = []
    hierarchy_reached = False
    hierarchy_dropped = 0
    hierarchy_excluded = 0
    if canonical_term is not None:
        try:
            hierarchy, hierarchy_excluded, hierarchy_reached, hierarchy_dropped = (
                await _hierarchy(canonical_term, anchor_words)
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Disease hierarchy lookup failed: %s", exc)
            hierarchy, hierarchy_reached = [], False

    related: list[DiseaseTerm] = []
    excluded_related = hierarchy_excluded
    seen = {normalize_term(canonical_term.label) if canonical_term else ""}
    for term in hierarchy:
        key = normalize_term(term.label)
        if key in seen:
            continue
        seen.add(key)
        related.append(term)
    for index, doc in ranked[1:]:
        term = _term(doc)
        if term is None:
            continue
        key = normalize_term(term.label)
        if key in seen:
            continue
        if not _doc_words(doc) & q_tokens:
            excluded_related += 1
            continue
        if canonical_term and _is_genetics_variant(term.label, canonical_term.label):
            excluded_related += 1
            continue
        seen.add(key)
        related.append(term)

    note = None
    if canonical_term is None:
        note = (
            "No concept in the disease ontology shares wording with this query, so "
            "MolTel reports no canonical term for it."
        )
    elif not hierarchy_reached:
        note = (
            "The ontology's child concepts of this term could not be read, so no "
            "standardized subtype relation is available for it; the subtype list "
            "uses the condition wording the retrieved records use."
        )
    elif hierarchy_dropped:
        note = (
            "The hierarchy was followed two levels below the matched concept; "
            f"{hierarchy_dropped} deeper child concept(s) were not read."
        )

    return DiseaseConcept(
        query=query,
        source_reached=True,
        hierarchy_reached=hierarchy_reached,
        retrieved_at=retrieved_at,
        canonical=canonical_term,
        related=related,
        excluded_related=excluded_related,
        note=note,
    )
