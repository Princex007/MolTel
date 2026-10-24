"""Disease view built from records that were already retrieved (spec §6.2, §6.3).

These tests hand the service a stubbed ontology concept and stubbed registry
records, so what is asserted is which wording a subtype comes from, which records
are attached to it, and what is said when nothing is attached.
"""

from __future__ import annotations

from models.schemas import (
    CandidateAnalytics,
    CandidateRecord,
    ClinicalTrial,
    DiseaseConcept,
    DiseaseTerm,
    EvidenceItem,
    TargetProfile,
    TrialRetrievalMetadata,
)
from services.disease_analytics import compute_disease_analytics


def _term(label, concept_id=None, synonyms=(), parent=None):
    return DiseaseTerm(
        label=label,
        concept_id=concept_id,
        ontology="mondo" if concept_id else None,
        synonyms=list(synonyms),
        parent=parent,
    )


def _trial(nct_id, conditions, title="", sponsor=None):
    return ClinicalTrial(
        nct_id=nct_id,
        title=title or f"Study {nct_id}",
        conditions=list(conditions),
        sponsor=sponsor,
    )


def _metadata(query="lung cancer", reached=True, records=0):
    return TrialRetrievalMetadata(
        query=query,
        source_reached=reached,
        records_returned=records,
        partial=True,
        retrieved_at="2026-10-23T00:00:00+00:00",
    )


def _candidates(*pairs):
    return CandidateAnalytics(
        distinct_candidates=len(pairs),
        metadata=_metadata(),
        records=[
            CandidateRecord(name=name, nct_ids=list(nct_ids), trials=len(nct_ids))
            for name, nct_ids in pairs
        ],
    )


_LUNG_CONCEPT = DiseaseConcept(
    query="lung cancer",
    source_reached=True,
    canonical=_term(
        "lung cancer", "MONDO:0008903", synonyms=["Lung Neoplasms", "cancers, lung"]
    ),
    related=[
        _term("non-small cell lung carcinoma", "MONDO:0005233", parent="lung carcinoma"),
        _term("small cell lung carcinoma", "MONDO:0008433", parent="lung carcinoma"),
        # The ontology files this one as a child of the matched term, which is the
        # only reason it is a subtype of it rather than another name for it.
        _term("lung carcinoma", "MONDO:0005138", parent="lung cancer"),
    ],
)


def _lung_fixture():
    trials = [
        _trial(
            "NCT1",
            ["Non-small Cell Lung Cancer (NSCLC)"],
            title="Pembrolizumab in advanced NSCLC",
            sponsor="Merck Sharp",
        ),
        _trial("NCT2", ["Lung Cancer", "Fatigue"], sponsor="AstraZeneca"),
        _trial("NCT3", ["Small Cell Lung Carcinoma"], sponsor="NIH"),
        _trial("NCT4", [], title="A study that names no condition"),
    ]
    evidence = [
        EvidenceItem(
            source="PubMed",
            source_type="literature",
            id="111",
            title="Checkpoint inhibitors in non-small cell lung cancer",
            abstract="Review of NSCLC immunotherapy.",
        ),
        EvidenceItem(
            source="EuropePMC",
            source_type="literature",
            id="222",
            title="Survival after lung cancer diagnosis",
            abstract="Registry analysis.",
        ),
    ]
    targets = [
        TargetProfile(
            accession="P00001",
            name="Programmed cell death protein 1",
            gene="PDCD1",
            function_summary="Studied in non-small cell lung cancer.",
        )
    ]
    return trials, evidence, targets


def test_a_broad_query_is_not_treated_as_one_homogeneous_condition():
    trials, evidence, targets = _lung_fixture()
    analytics = compute_disease_analytics(
        "lung cancer", _LUNG_CONCEPT, trials, evidence, _candidates(
            ("Pembrolizumab", ["NCT1"]), ("Metformin", ["NCT2"])
        ), targets, _metadata(records=4)
    )

    by_label = {s.label: s for s in analytics.subtypes}
    nsclc = by_label["Non-small Cell Lung Cancer (NSCLC)"]
    assert nsclc.trial_nct_ids == ["NCT1"]
    # A candidate and a company attach through a trial already on the subtype.
    assert nsclc.candidate_names == ["Pembrolizumab"]
    assert nsclc.company_names == ["Merck Sharp"]
    assert nsclc.paper_keys == ["PubMed:111"]
    assert nsclc.target_accessions == ["P00001"]
    # The query wording itself is the top of the list, not a subtype of it.
    assert "lung cancer" not in {s.label.casefold() for s in analytics.subtypes}
    assert analytics.canonical_term == "lung cancer"
    assert "MONDO:0008903" in analytics.canonical_term_provenance
    assert analytics.trials_considered == 4


def test_word_order_and_plural_are_folded_but_a_partial_overlap_is_not_a_match():
    concept = DiseaseConcept(
        query="diabetes mellitus",
        source_reached=True,
        canonical=_term("diabetes mellitus", "MONDO:0005015"),
        related=[
            _term("type 2 diabetes mellitus", "MONDO:0005148", parent="diabetes mellitus")
        ],
    )
    trials = [
        _trial("NCT1", ["Diabetes Mellitus, Type 2"]),
        _trial("NCT2", ["Type 1 Diabetes Mellitus"]),
        _trial("NCT3", ["Lung Neoplasms"]),
    ]
    analytics = compute_disease_analytics(
        "diabetes mellitus", concept, trials, [], None, [], _metadata("diabetes mellitus")
    )

    subtype = next(s for s in analytics.subtypes if s.label == "type 2 diabetes mellitus")
    assert subtype.trial_nct_ids == ["NCT1"]
    assert subtype.condition_labels == ["Diabetes Mellitus, Type 2"]
    assert subtype.origin == "both"
    # Type 1 is a subtype too, named only by the registry's own wording. A trial
    # for a different disease is attached to neither.
    registry_only = [s for s in analytics.subtypes if s.origin == "registry condition wording"]
    assert [s.label for s in registry_only] == ["Type 1 Diabetes Mellitus"]
    assert registry_only[0].trial_nct_ids == ["NCT2"]
    assert analytics.subtypes_with_records == 2


def test_a_plural_registry_label_matches_the_singular_concept_wording():
    concept = DiseaseConcept(
        query="lung cancer",
        source_reached=True,
        canonical=_term("lung cancer", "MONDO:0008903", synonyms=["lung neoplasm"]),
    )
    trials = [_trial("NCT1", ["Lung Neoplasms"])]
    analytics = compute_disease_analytics(
        "lung cancer", concept, trials, [], None, [], _metadata()
    )

    # "Lung Neoplasms" is the concept's own synonym wording, not a subtype of it,
    # so it is neither listed as a subtype nor dropped from the counts.
    assert analytics.subtypes == []
    assert analytics.unmatched_condition_labels == []
    assert analytics.trials_with_condition_label == 1


def test_a_negated_subtype_is_not_filed_under_the_wording_it_negates():
    trials, evidence, targets = _lung_fixture()
    analytics = compute_disease_analytics(
        "lung cancer", _LUNG_CONCEPT, trials, evidence, None, targets, _metadata()
    )

    by_label = {s.label: s for s in analytics.subtypes}
    nsclc = by_label["non-small cell lung carcinoma"]
    assert nsclc.refines == "lung carcinoma"
    assert by_label["small cell lung carcinoma"].refines == "lung carcinoma"
    assert by_label["lung carcinoma"].refines == "lung cancer"
    # Both cell carcinomas hang one level below the term the ontology parents them
    # under, not beside it.
    assert nsclc.level == 2
    assert by_label["small cell lung carcinoma"].level == 2


def test_a_subtype_with_no_retrieved_trial_says_what_that_does_not_mean():
    concept = DiseaseConcept(
        query="lung cancer",
        source_reached=True,
        canonical=_term("lung cancer", "MONDO:0008903"),
        related=[
            _term("small cell lung carcinoma", "MONDO:0008433", parent="lung carcinoma"),
            _term("large cell lung carcinoma", "MONDO:0008904", parent="lung carcinoma"),
        ],
    )
    trials = [_trial("NCT1", ["Lung Cancer"])]
    analytics = compute_disease_analytics("lung cancer", concept, trials, [], None, [], _metadata())

    empty = [s for s in analytics.subtypes if not s.trial_nct_ids]
    assert empty
    assert all("not that research on this subtype is missing" in s.availability_note for s in empty)
    assert analytics.subtypes_without_records == len(empty)


def test_condition_strings_that_name_no_subtype_are_reported_not_dropped():
    trials, evidence, targets = _lung_fixture()
    analytics = compute_disease_analytics(
        "lung cancer", _LUNG_CONCEPT, trials, evidence, None, targets, _metadata()
    )

    labels = {bucket.label: bucket.count for bucket in analytics.unmatched_condition_labels}
    assert labels["Fatigue"] == 1
    # The trial that names no condition at all is counted, not assumed to match.
    assert analytics.trials_without_condition_label == 1
    assert analytics.trials_with_condition_label == 3


def test_no_canonical_term_is_invented_when_the_ontology_cannot_be_consulted():
    trials, evidence, targets = _lung_fixture()
    concept = DiseaseConcept(
        query="lung cancer",
        source_reached=False,
        note="The disease ontology could not be reached.",
    )
    analytics = compute_disease_analytics(
        "lung cancer", concept, trials, evidence, None, targets, _metadata()
    )

    assert analytics.ontology_reached is False
    # Subtypes then come from the registry's own condition strings.
    assert {s.origin for s in analytics.subtypes} == {"registry condition wording"}
    assert analytics.concept is None
    assert any("could not be consulted" in line for line in analytics.limitations)
    assert "registry wording, not a canonical disease term" in analytics.canonical_term_provenance


def test_a_reachable_registry_that_returned_nothing_is_stated_as_that():
    analytics = compute_disease_analytics(
        "lung cancer",
        _LUNG_CONCEPT,
        [],
        [],
        None,
        [],
        _metadata(reached=False),
    )

    assert analytics.canonical_term == "lung cancer"
    assert analytics.trials_considered == 0
    assert analytics.subtypes_with_records == 0
    assert any("could not be consulted" in line for line in analytics.limitations)


# ---------------------------------------------------------------------------
# Wording that must not be mistaken for a subtype (spec §6.2)
# ---------------------------------------------------------------------------


def test_a_term_broader_than_the_query_is_not_listed_as_one_of_its_subtypes():
    """A lung cancer trial set also treats 'Cancer'; that is the parent, not a subtype."""
    trials = [
        _trial("NCT1", ["Cancer", "Non-small Cell Lung Cancer (NSCLC)"]),
        _trial("NCT2", ["Cancer"]),
    ]
    analytics = compute_disease_analytics(
        "lung cancer", _LUNG_CONCEPT, trials, [], None, [], _metadata()
    )

    assert "Cancer" not in {s.label for s in analytics.subtypes}
    # Reported as other condition wording, with the trials that use it.
    residual = {b.label: b.count for b in analytics.unmatched_condition_labels}
    assert residual["Cancer"] == 2
    nsclc = next(s for s in analytics.subtypes if s.trial_nct_ids)
    assert nsclc.trial_nct_ids == ["NCT1"]


def test_a_concept_the_ontology_does_not_file_as_a_child_is_not_listed_as_a_subtype():
    """Searching lung cancer returns "carcinoma", which is not a subtype of it.

    The ontology's search answers with the classes a disease belongs to as well as
    its divisions, and the wording it returns says nothing about which is which:
    "carcinoma" would count skin and breast studies under a lung query, and would
    then be reused as a name to match records against, dragging every organ's
    carcinoma in. Only the relation the ontology itself publishes is used.
    """
    concept = DiseaseConcept(
        query="lung cancer",
        source_reached=True,
        canonical=_term(
            "lung cancer",
            "MONDO:0008903",
            synonyms=["cancer of lung", "malignant lung neoplasm"],
        ),
        related=[
            _term("carcinoma", "MONDO:0004993"),
            _term("ovarian carcinoma", "MONDO:0021072"),
            _term("lung neoplasm", "MONDO:0024365"),
            _term("lung adenocarcinoma", "MONDO:0005631", parent="lung carcinoma"),
        ],
    )
    trials = [
        _trial("NCT1", ["Lung Carcinoma", "Skin Carcinoma", "Lung Neoplasm"]),
        _trial("NCT2", ["Ovarian Cancer"]),
        _trial("NCT3", ["Lung Adenocarcinoma"]),
    ]
    analytics = compute_disease_analytics(
        "lung cancer", concept, trials, [], None, [], _metadata()
    )

    by_label = {s.label: s for s in analytics.subtypes}
    assert "carcinoma" not in by_label
    assert "ovarian carcinoma" not in by_label
    assert "lung neoplasm" not in by_label
    # The concept the ontology does file as a child still carries its own records.
    assert by_label["lung adenocarcinoma"].trial_nct_ids == ["NCT3"]
    assert any("state no relation" in line for line in analytics.limitations)
    # And a left-out concept's wording is not reused to match records: three
    # returned concepts stated nothing, so nothing is filed under their names.
    assert len(analytics.subtypes) == 1
    assert "Skin Carcinoma" not in {
        label for s in analytics.subtypes for label in s.condition_labels
    }


def test_a_denied_word_does_not_attach_a_record_to_the_subtype_that_negates_it():
    """'Small cell lung carcinoma' cannot be proved by a non-small-cell record."""
    trials, evidence, targets = _lung_fixture()
    analytics = compute_disease_analytics(
        "lung cancer", _LUNG_CONCEPT, trials, evidence, None, targets, _metadata()
    )

    by_label = {s.label: s for s in analytics.subtypes}
    assert "NCT3" in by_label["small cell lung carcinoma"].trial_nct_ids
    nsclc = by_label["Non-small Cell Lung Cancer (NSCLC)"]
    assert "NCT3" not in nsclc.trial_nct_ids
    assert nsclc.condition_labels == ["Non-small Cell Lung Cancer (NSCLC)"]


def test_a_registry_abbreviation_is_filed_under_the_concept_that_records_it():
    """'NSCLC' is a name the concept carries, so it is not a second subtype."""
    concept = DiseaseConcept(
        query="lung cancer",
        source_reached=True,
        canonical=_term("lung cancer", "MONDO:0008903"),
        related=[
            _term(
                "non-small cell lung carcinoma",
                "MONDO:0005233",
                synonyms=["NSCLC", "non-small cell lung cancer"],
                parent="lung carcinoma",
            )
        ],
    )
    trials = [
        _trial("NCT1", ["NSCLC"], sponsor="Merck Sharp"),
        _trial("NCT2", ["Non Small Cell Lung Cancer"], sponsor="Pfizer"),
    ]
    analytics = compute_disease_analytics(
        "lung cancer", concept, trials, [], None, [], _metadata()
    )

    assert [s.label for s in analytics.subtypes] == ["non-small cell lung carcinoma"]
    subtype = analytics.subtypes[0]
    assert subtype.origin == "both"
    assert subtype.trial_nct_ids == ["NCT1", "NCT2"]
    assert subtype.company_names == ["Merck Sharp", "Pfizer"]
    assert subtype.condition_labels == ["NSCLC", "Non Small Cell Lung Cancer"]


def test_a_hierarchy_relation_from_the_ontology_is_reported_as_such():
    """A parent the source states outranks a parent inferred from wording."""
    concept = DiseaseConcept(
        query="lung cancer",
        source_reached=True,
        canonical=_term("lung cancer", "MONDO:0008903"),
        related=[
            _term("lung carcinoma", "MONDO:0005138", parent="lung cancer"),
            _term(
                "lung adenocarcinoma",
                "MONDO:0005061",
                parent="lung carcinoma",
            ),
        ],
    )
    trials = [_trial("NCT1", ["Lung Adenocarcinoma"])]
    analytics = compute_disease_analytics(
        "lung cancer", concept, trials, [], None, [], _metadata()
    )

    by_label = {s.label: s for s in analytics.subtypes}
    assert by_label["lung carcinoma"].refines == "lung cancer"
    assert by_label["lung carcinoma"].refines_source == "standardized hierarchy"
    assert by_label["lung adenocarcinoma"].refines == "lung carcinoma"
    assert by_label["lung adenocarcinoma"].level == 2
    assert by_label["lung carcinoma"].level == 1


def test_records_that_spell_a_condition_out_are_not_matched_by_an_abbreviation():
    """A subtype named 'NSCLC' is not proved by a record saying 'Lung Cancer'."""
    concept = DiseaseConcept(
        query="lung cancer",
        source_reached=True,
        canonical=_term("lung cancer", "MONDO:0008903"),
        related=[
            _term(
                "bronchus cancer",
                "MONDO:0001672",
                synonyms=["BRC"],
                parent="respiratory organ cancer",
            )
        ],
    )
    trials = [_trial("NCT1", ["Lung Cancer"]), _trial("NCT2", ["BRC"])]
    analytics = compute_disease_analytics(
        "lung cancer", concept, trials, [], None, [], _metadata()
    )

    subtype = next(s for s in analytics.subtypes if s.label == "bronchus cancer")
    assert subtype.trial_nct_ids == ["NCT2"]


def test_a_category_word_in_a_synonym_does_not_make_a_subtype_of_every_record():
    """MONDO writes "meningioma (disease) of lung"; the bracketed word names the
    kind of record, not the condition, so it cannot attach a trial that only says
    it studies an oncologic disease."""
    concept = DiseaseConcept(
        query="lung cancer",
        source_reached=True,
        canonical=_term("lung cancer", "MONDO:0008903"),
        related=[
            _term(
                "lung meningioma",
                "MONDO:0003638",
                synonyms=["meningioma (disease) of lung", "pulmonary meningioma"],
                parent="lung disease",
            )
        ],
    )
    trials = [
        _trial("NCT1", ["Oncologic Diseases"], title="A study of carcinoid tumours"),
        _trial("NCT2", ["Pulmonary Meningioma"], title="Meningioma followed up"),
    ]
    analytics = compute_disease_analytics(
        "lung cancer", concept, trials, [], None, [], _metadata()
    )

    by_label = {s.label: s for s in analytics.subtypes}
    assert by_label["lung meningioma"].trial_nct_ids == ["NCT2"]
    assert by_label["lung meningioma"].condition_labels == ["Pulmonary Meningioma"]
    # The category wording is neither a subtype of lung cancer nor attached to one.
    assert "Oncologic Diseases" not in by_label
    assert [b.label for b in analytics.unmatched_condition_labels] == ["Oncologic Diseases"]
