"""Disease concept lookup against a stubbed ontology API.

No test here reaches the network: OLS4 is answered by respx, so what is asserted
is how the lookup reports what the ontology said — including when it says
nothing usable.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from integrations import disease_ontology

OLS_URL = "https://www.ebi.ac.uk/ols4/api/search"
OLS_CHILDREN_URL = "https://www.ebi.ac.uk/ols4/api/ontologies/mondo/children"


def _doc(label, obo_id, synonyms=(), description=(), iri=None, has_children=False):
    return {
        "label": label,
        "obo_id": obo_id,
        "iri": iri or f"http://purl.obolibrary.org/obo/{obo_id.replace(':', '_')}",
        "ontology_name": "mondo",
        "description": list(description),
        "exact_synonyms": list(synonyms),
        "has_children": has_children,
    }


def _response(docs):
    return httpx.Response(200, json={"response": {"numFound": len(docs), "docs": docs}})


def _children_response(docs):
    return httpx.Response(
        200, json={"_embedded": {"terms": docs}, "page": {"totalElements": len(docs)}}
    )


@pytest.mark.asyncio
@respx.mock
async def test_the_exact_label_is_chosen_as_canonical_and_numbered_loci_are_not():
    respx.get(OLS_URL).mock(
        return_value=_response(
            [
                _doc("Alzheimer disease 3", "MONDO:0011913"),
                _doc("Alzheimer disease 2", "MONDO:0007089"),
                _doc("Alzheimer disease", "MONDO:0004975", synonyms=["Alzheimer's disease"], description=["A neurodegenerative disease."]),
                _doc("lung cancer susceptibility 1", "MONDO:0012159"),
            ]
        )
    )

    concept = await disease_ontology.lookup_disease("alzheimer")

    assert concept.source_reached is True
    assert concept.canonical is not None
    # The bare disease concept, not the linkage locus that ranks first.
    assert concept.canonical.label == "Alzheimer disease"
    assert concept.canonical.concept_id == "MONDO:0004975"
    assert concept.canonical.synonyms == ["Alzheimer's disease"]
    assert "MONDO%3A0004975" in (concept.canonical.url or "")
    # "Alzheimer disease 2/3" add only a number, and "lung cancer susceptibility 1"
    # adds a genetics word: none is a clinical subtype of Alzheimer disease.
    assert concept.related == []
    assert concept.excluded_related == 3


@pytest.mark.asyncio
@respx.mock
async def test_association_study_synonyms_are_counted_out_rather_than_shown():
    respx.get(OLS_URL).mock(
        return_value=_response(
            [
                _doc(
                    "lung cancer",
                    "MONDO:0008903",
                    synonyms=[
                        "Lung Neoplasms",
                        "cancers, lung",
                        "lung cancer, susceptibility to, autosomal dominant, somatic mutation",
                        "a very long synonym string that describes a study of the disease rather than the disease itself",
                    ],
                )
            ]
        )
    )

    concept = await disease_ontology.lookup_disease("lung cancer")

    assert concept.canonical is not None
    assert concept.canonical.synonyms == ["Lung Neoplasms", "cancers, lung"]
    assert concept.canonical.excluded_synonyms == 2


@pytest.mark.asyncio
@respx.mock
async def test_a_concept_that_shares_no_wording_is_not_reported_as_the_canonical_term():
    respx.get(OLS_URL).mock(
        return_value=_response([_doc("Arterial calcification", "MONDO:0010101")])
    )

    concept = await disease_ontology.lookup_disease(" Rezafungin resistance")

    assert concept.source_reached is True
    assert concept.canonical is None
    assert concept.related == []
    assert "no concept" in (concept.note or "").lower()


@pytest.mark.asyncio
@respx.mock
async def test_a_query_that_is_a_recorded_name_maps_to_that_concept():
    """A synonym query must not land on the concept that merely looks word-similar."""
    respx.get(OLS_URL).mock(
        return_value=_response(
            [
                # These two carry the query's words inside a longer name, so they
                # match the query less well than the concept recorded under it.
                _doc(
                    "lung hilum cancer",
                    "MONDO:0004332",
                    synonyms=["malignant neoplasm of lung hilum", "malignant hilar lung neoplasm"],
                ),
                _doc(
                    "lung cancer",
                    "MONDO:0008903",
                    synonyms=["malignant neoplasm of lung", "malignant lung tumour"],
                ),
                _doc(
                    "malignant superior sulcus neoplasm",
                    "MONDO:0006883",
                    synonyms=["malignant superior sulcus neoplasm of lung"],
                ),
            ]
        )
    )

    concept = await disease_ontology.lookup_disease("malignant neoplasm of lung")

    assert concept.canonical is not None
    assert concept.canonical.label == "lung cancer"
    assert concept.canonical.concept_id == "MONDO:0008903"


@pytest.mark.asyncio
@respx.mock
async def test_an_abbreviation_is_read_as_the_name_of_the_concept_that_records_it():
    respx.get(OLS_URL).mock(
        return_value=_response(
            [
                _doc(
                    "non-small cell lung carcinoma",
                    "MONDO:0005233",
                    synonyms=["NSCLC - non-small cell lung cancer", "NSCLC"],
                ),
                _doc("squamous cell lung carcinoma", "MONDO:0005097"),
            ]
        )
    )

    concept = await disease_ontology.lookup_disease("NSCLC")

    assert concept.canonical is not None
    assert concept.canonical.label == "non-small cell lung carcinoma"


@pytest.mark.asyncio
@respx.mock
async def test_an_unreachable_ontology_says_it_could_not_be_consulted():
    respx.get(OLS_URL).mock(return_value=httpx.Response(500))

    concept = await disease_ontology.lookup_disease("lung cancer")

    assert concept.source_reached is False
    assert concept.canonical is None
    assert "could not be reached" in (concept.note or "")


@pytest.mark.asyncio
@respx.mock
async def test_an_empty_ontology_result_is_not_read_as_a_failed_lookup():
    respx.get(OLS_URL).mock(return_value=_response([]))

    concept = await disease_ontology.lookup_disease("some condition")

    assert concept.source_reached is True
    assert concept.canonical is None
    assert "no concept" in (concept.note or "").lower()


# ---------------------------------------------------------------------------
# The ontology's own subtype hierarchy (spec §6.2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_child_concepts_are_read_from_the_ontology_and_keep_their_parent():
    respx.get(OLS_URL).mock(
        return_value=_response([_doc("lung cancer", "MONDO:0008903", has_children=True)])
    )
    routes = {
        "MONDO_0008903": [_doc("lung carcinoma", "MONDO:0005138", has_children=True)],
        "MONDO_0005138": [
            _doc(
                "non-small cell lung carcinoma",
                "MONDO:0005233",
                synonyms=["NSCLC", "non-small cell lung cancer"],
            ),
            _doc("gastric adenocarcinoma", "MONDO:0001040"),
        ],
    }

    def children(request):
        iri = request.url.params["iri"]
        short_form = iri.rsplit("/", 1)[-1]
        docs = routes.get(short_form)
        if docs is None:
            return httpx.Response(404)
        return _children_response(docs)

    respx.get(OLS_CHILDREN_URL).mock(side_effect=children)

    concept = await disease_ontology.lookup_disease("lung cancer")

    assert concept.hierarchy_reached is True
    by_label = {term.label: term for term in concept.related}
    assert by_label["lung carcinoma"].parent == "lung cancer"
    assert by_label["lung carcinoma"].parent_concept_id == "MONDO:0008903"
    assert by_label["non-small cell lung carcinoma"].parent == "lung carcinoma"
    # A child two levels down that does not name this disease at all is left out,
    # and said to be left out.
    assert "gastric adenocarcinoma" not in by_label
    assert concept.excluded_related == 1
    assert by_label["non-small cell lung carcinoma"].synonyms == [
        "NSCLC",
        "non-small cell lung cancer",
    ]


@pytest.mark.asyncio
@respx.mock
async def test_a_hierarchy_that_cannot_be_read_does_not_lose_the_matched_term():
    respx.get(OLS_URL).mock(
        return_value=_response([_doc("lung cancer", "MONDO:0008903", has_children=True)])
    )
    respx.get(OLS_CHILDREN_URL).mock(return_value=httpx.Response(500))

    concept = await disease_ontology.lookup_disease("lung cancer")

    assert concept.source_reached is True
    assert concept.canonical is not None
    assert concept.hierarchy_reached is False
    assert concept.related == []
    assert "child concepts" in (concept.note or "")


@pytest.mark.asyncio
@respx.mock
async def test_a_child_that_only_adds_a_genetics_word_is_not_a_subtype():
    respx.get(OLS_URL).mock(
        return_value=_response([_doc("lung cancer", "MONDO:0008903", has_children=True)])
    )
    respx.get(OLS_CHILDREN_URL).mock(
        return_value=_children_response(
            [
                _doc("lung cancer susceptibility 3", "MONDO:0024592"),
                _doc("lung carcinoma", "MONDO:0005138"),
            ]
        )
    )

    concept = await disease_ontology.lookup_disease("lung cancer")

    assert [term.label for term in concept.related] == ["lung carcinoma"]
    assert concept.excluded_related == 1
