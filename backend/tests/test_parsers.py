"""Unit tests for all six integration parsers using respx mocks."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

# ---------------------------------------------------------------------------
# PubChem
# ---------------------------------------------------------------------------

PUBCHEM_PROPERTY_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/aspirin/property/MolecularFormula,MolecularWeight,ConnectivitySMILES,SMILES,IUPACName,InChIKey/JSON"
PUBCHEM_SYNONYMS_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/2244/synonyms/JSON"
PUBCHEM_NOTFOUND_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/notarealcompound123/property/MolecularFormula,MolecularWeight,ConnectivitySMILES,SMILES,IUPACName,InChIKey/JSON"

# PubChem renamed CanonicalSMILES -> ConnectivitySMILES and IsomericSMILES -> SMILES.
PUBCHEM_PROPERTY_RESPONSE = {
    "PropertyTable": {
        "Properties": [
            {
                "CID": 2244,
                "MolecularFormula": "C9H8O4",
                "MolecularWeight": "180.16",
                "ConnectivitySMILES": "CC(=O)OC1=CC=CC=C1C(=O)O",
                "SMILES": "CC(=O)Oc1ccccc1C(=O)O",
                "IUPACName": "2-acetyloxybenzoic acid",
                "InChIKey": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
            }
        ]
    }
}

PUBCHEM_SYNONYMS_RESPONSE = {
    "InformationList": {
        "Information": [{"Synonym": ["Aspirin", "Acetylsalicylic acid", "ASA"]}]
    }
}


@pytest.mark.asyncio
@respx.mock
async def test_pubchem_search_compound():
    """Mock PubChem PUG REST responses and assert CompoundProfile fields."""
    respx.get(PUBCHEM_PROPERTY_URL).mock(
        return_value=httpx.Response(200, json=PUBCHEM_PROPERTY_RESPONSE)
    )
    respx.get(PUBCHEM_SYNONYMS_URL).mock(
        return_value=httpx.Response(200, json=PUBCHEM_SYNONYMS_RESPONSE)
    )

    from integrations.pubchem import search_compound

    result = await search_compound("aspirin")

    assert result is not None
    assert result.cid == "2244"
    assert result.molecular_formula == "C9H8O4"
    assert result.canonical_smiles == "CC(=O)OC1=CC=CC=C1C(=O)O"
    assert result.isomeric_smiles == "CC(=O)Oc1ccccc1C(=O)O"
    assert result.iupac_name == "2-acetyloxybenzoic acid"
    assert result.inchi_key == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
    assert "Aspirin" in result.synonyms


@pytest.mark.asyncio
@respx.mock
async def test_pubchem_legacy_smiles_keys():
    """Legacy CanonicalSMILES/IsomericSMILES response keys are still parsed."""
    respx.get(PUBCHEM_PROPERTY_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "PropertyTable": {
                    "Properties": [
                        {
                            "CID": 2244,
                            "CanonicalSMILES": "legacy-canonical",
                            "IsomericSMILES": "legacy-isomeric",
                        }
                    ]
                }
            },
        )
    )
    respx.get(PUBCHEM_SYNONYMS_URL).mock(
        return_value=httpx.Response(200, json=PUBCHEM_SYNONYMS_RESPONSE)
    )

    from integrations.pubchem import search_compound

    result = await search_compound("aspirin")

    assert result is not None
    assert result.canonical_smiles == "legacy-canonical"
    assert result.isomeric_smiles == "legacy-isomeric"


@pytest.mark.asyncio
@respx.mock
async def test_pubchem_encodes_compound_name():
    """Names with reserved characters must be percent-encoded in the URL path."""
    route = respx.get(
        "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
        "vitamin%20c%20%28ascorbic%20acid%29/property/"
        "MolecularFormula,MolecularWeight,ConnectivitySMILES,SMILES,IUPACName,InChIKey/JSON"
    ).mock(return_value=httpx.Response(404, text="Not Found"))

    from integrations.pubchem import search_compound

    assert await search_compound("vitamin c (ascorbic acid)") is None
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_pubchem_not_found():
    """Mock a 404 response and assert that search_compound returns None."""
    respx.get(PUBCHEM_NOTFOUND_URL).mock(
        return_value=httpx.Response(404, text="Not Found")
    )

    from integrations.pubchem import search_compound

    result = await search_compound("notarealcompound123")
    assert result is None


# ---------------------------------------------------------------------------
# PubMed
# ---------------------------------------------------------------------------

PUBMED_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

PUBMED_ESEARCH_RESPONSE = {
    "esearchresult": {
        "idlist": ["12345678"],
        "count": "1",
    }
}

PUBMED_EFETCH_XML = """<?xml version="1.0" ?>
<!DOCTYPE PubmedArticleSet PUBLIC "-//NLM//DTD PubMedArticle, 1st January 2019//EN" "">
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>12345678</PMID>
      <Article>
        <ArticleTitle>Clemizole inhibits TRPC5 channels</ArticleTitle>
        <AuthorList>
          <Author>
            <LastName>Smith</LastName>
            <ForeName>John</ForeName>
          </Author>
        </AuthorList>
        <Abstract>
          <AbstractText Label="BACKGROUND">TRPC5 channels are implicated in neurodegeneration.</AbstractText>
          <AbstractText Label="METHODS">This study demonstrates the inhibition of TRPC5 by Clemizole.</AbstractText>
        </Abstract>
        <PublicationTypeList>
          <PublicationType>Journal Article</PublicationType>
          <PublicationType>Randomized Controlled Trial</PublicationType>
        </PublicationTypeList>
        <Journal>
          <JournalIssue>
            <ISOAbbreviation>J Neurosci</ISOAbbreviation>
            <PubDate>
              <Year>2023</Year>
            </PubDate>
          </JournalIssue>
        </Journal>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="doi">10.1234/test.doi</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>"""


@pytest.mark.asyncio
@respx.mock
async def test_pubmed_search_literature():
    """Mock esearch + efetch responses and assert EvidenceItem fields."""
    respx.get(PUBMED_ESEARCH_URL).mock(
        return_value=httpx.Response(200, json=PUBMED_ESEARCH_RESPONSE)
    )
    respx.get(PUBMED_EFETCH_URL).mock(
        return_value=httpx.Response(200, text=PUBMED_EFETCH_XML)
    )

    from integrations.pubmed import search_literature

    results = await search_literature("Clemizole TRPC5")

    assert len(results) == 1
    item = results[0]
    assert item.source == "PubMed"
    assert item.id == "12345678"
    assert "Clemizole" in item.title
    assert item.year == 2023
    assert "Smith John" in item.authors
    assert item.url == "https://pubmed.ncbi.nlm.nih.gov/12345678/"

    # Structured abstracts carry one AbstractText per section label.
    assert item.abstract == (
        "BACKGROUND: TRPC5 channels are implicated in neurodegeneration. "
        "METHODS: This study demonstrates the inhibition of TRPC5 by Clemizole."
    )
    # Publication type drives the evidence badge — a trial must not read as a review.
    assert item.evidence_type.value == "randomized_controlled_trial"
    assert item.metadata["journal"] == "J Neurosci"


@pytest.mark.asyncio
@respx.mock
async def test_pubmed_reads_stated_dates_identifiers_and_types():
    """The literature views need a publication date, an indexing date and every id.

    ArticleDate is the publisher's date and states a day; History/PubmedPubDate
    with PubStatus="entrez" is when the record entered the database. The two are
    different claims and are parsed apart, and the PMC id is kept because it is
    what merges this record with Europe PMC's copy of the same paper.
    """
    respx.get(PUBMED_ESEARCH_URL).mock(
        return_value=httpx.Response(200, json=PUBMED_ESEARCH_RESPONSE)
    )
    respx.get(PUBMED_EFETCH_URL).mock(
        return_value=httpx.Response(
            200,
            text="""<?xml version="1.0" ?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>12345678</PMID>
      <Article>
        <ArticleTitle>TRPC5 blockade in models</ArticleTitle>
        <Journal>
          <JournalIssue>
            <PubDate><Year>2023</Year><Month>May</Month></PubDate>
          </JournalIssue>
          <ArticleDate><Year>2023</Year><Month>05</Month><Day>11</Day></ArticleDate>
        </Journal>
        <PublicationTypeList>
          <PublicationType>Journal Article</PublicationType>
          <PublicationType>Retraction of Publication</PublicationType>
        </PublicationTypeList>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <History>
        <PubMedPubDate PubStatus="pubmed">
          <Year>2023</Year><Month>5</Month><Day>12</Day>
        </PubMedPubDate>
        <PubMedPubDate PubStatus="entrez">
          <Year>2023</Year><Month>5</Month><Day>10</Day>
        </PubMedPubDate>
      </History>
      <ArticleIdList>
        <ArticleId IdType="pubmed">12345678</ArticleId>
        <ArticleId IdType="pmc">PMC9988776</ArticleId>
        <ArticleId IdType="doi">https://doi.org/10.5555/td.2023.011</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>""",
        )
    )

    from integrations.pubmed import search_literature

    item = (await search_literature("TRPC5"))[0]

    assert item.published_on == "2023-05-11"
    assert item.published_precision == "day"
    assert item.year == 2023
    # Entrez, not the "pubmed" history entry, and never used as a publication date
    assert item.indexed_on == "2023-05-10"
    assert item.indexed_field == "entrez"
    assert item.pmid == "12345678"
    assert item.pmcid == "PMC9988776"
    # The stored DOI is the bare identifier even though the source wrapped it in a URL
    assert item.doi == "10.5555/td.2023.011"
    assert item.publication_types == ["Journal Article", "Retraction of Publication"]
    # A notice about a record outranks what the record claims to be
    assert item.evidence_type.value == "correction_or_retraction"
    # Europe PMC does not state open access for PubMed's copy, so nothing is assumed
    assert item.open_access is None
    assert item.links == [
        "https://pubmed.ncbi.nlm.nih.gov/12345678/",
        "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9988776/",
        "https://doi.org/10.5555/td.2023.011",
    ]


@pytest.mark.asyncio
@respx.mock
async def test_pubmed_keeps_a_year_only_date_a_year():
    """A journal stating only a year is not padded into a date nobody reported."""
    respx.get(PUBMED_ESEARCH_URL).mock(
        return_value=httpx.Response(200, json=PUBMED_ESEARCH_RESPONSE)
    )
    respx.get(PUBMED_EFETCH_URL).mock(
        return_value=httpx.Response(200, text=PUBMED_EFETCH_XML)
    )

    from integrations.pubmed import search_literature

    item = (await search_literature("Clemizole TRPC5"))[0]

    assert item.published_on == "2023"
    assert item.published_precision == "year"
    # The mocked record states no indexing date at all, which is left blank
    assert item.indexed_on is None
    assert item.pmcid is None


# ---------------------------------------------------------------------------
# Europe PMC
# ---------------------------------------------------------------------------
EUROPEPMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

EUROPEPMC_SEARCH_RESPONSE = {
    "resultList": {
        "result": [
            {
                "pmid": "99887766",
                "pmcid": "PMC1234567",
                "doi": "10.9999/epmc.2023",
                "title": "TRPC5 in neurodegeneration",
                "authorString": "Jones A, Williams B.",
                "pubYear": "2022",
                "abstractText": "Europe PMC abstract text here.",
                "journalInfo": {"journal": {"title": "Journal of Neuroscience"}},
                "pubTypeList": {"pubType": ["Research Support", "Journal Article"]},
            }
        ]
    }
}


@pytest.mark.asyncio
@respx.mock
async def test_europepmc_search():
    """Mock Europe PMC search JSON and assert EvidenceItem list."""
    route = respx.get(EUROPEPMC_SEARCH_URL).mock(
        return_value=httpx.Response(200, json=EUROPEPMC_SEARCH_RESPONSE)
    )

    from integrations.europepmc import search_literature

    results = await search_literature("TRPC5")

    assert len(results) == 1
    item = results[0]
    assert item.source == "EuropePMC"
    assert item.id == "99887766"
    assert item.title == "TRPC5 in neurodegeneration"
    assert item.year == 2022
    assert "Jones A" in item.authors
    assert item.url == "https://europepmc.org/article/MED/99887766"

    # 'lite' responses omit abstracts, which the ranking and UI both need.
    assert route.calls[0].request.url.params["resultType"] == "core"
    assert item.abstract == "Europe PMC abstract text here."
    assert item.metadata["journal"] == "Journal of Neuroscience"
    # "Research Support" and "Journal Article" state no study design, so the
    # record stays unclassified instead of being labelled a review by default.
    assert item.evidence_type.value == "other"


@pytest.mark.asyncio
@respx.mock
async def test_europepmc_reports_open_access_and_its_own_dates():
    """isOpenAccess, the print date and the indexing date are all on the record.

    Europe PMC states an open-access flag, so it is captured; a record it says
    nothing about stays unknown rather than being read as closed. citedByCount is
    returned by the same API and is deliberately not parsed: a citation count is
    not a measure of how trustworthy a study was.
    """
    respx.get(EUROPEPMC_SEARCH_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "resultList": {
                    "result": [
                        {
                            "pmid": "33445566",
                            "pmcid": "PMC8899001",
                            "doi": "10.1000/oh.2024",
                            "title": "A guideline for TRPC5 reporting",
                            "authorString": "Patel R, Okafor C.",
                            "pubYear": "2024",
                            "firstPublicationDate": "2024-02-03",
                            "electronicPublicationDate": "2024-01-28",
                            "firstIndexDate": "2024-03-01",
                            "isOpenAccess": "Y",
                            "inEPMC": "Y",
                            "citedByCount": 41,
                            "abstractText": "Consensus statements.",
                            "journalInfo": {"journal": {"title": "Reports"}},
                            "pubTypeList": {
                                "pubType": ["Guideline", "Journal Article"]
                            },
                        }
                    ]
                }
            },
        )
    )

    from integrations.europepmc import search_literature

    item = (await search_literature("TRPC5 guideline"))[0]

    # The print date the source states is the publication date, not the earlier
    # electronic one
    assert item.published_on == "2024-02-03"
    assert item.published_precision == "day"
    assert item.indexed_on == "2024-03-01"
    assert item.indexed_field == "firstIndexDate"
    assert item.open_access is True
    assert item.pmcid == "PMC8899001"
    assert item.publication_types == ["Guideline", "Journal Article"]
    assert item.evidence_type.value == "literature_review"
    assert "cited" not in item.metadata
    assert item.links == [
        "https://pubmed.ncbi.nlm.nih.gov/33445566/",
        "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8899001/",
        "https://doi.org/10.1000/oh.2024",
        "https://europepmc.org/article/MED/33445566",
    ]


@pytest.mark.asyncio
@respx.mock
async def test_europepmc_leaves_open_access_unknown_when_unstated():
    """The mocked record states no open-access flag, so nothing is assumed."""
    respx.get(EUROPEPMC_SEARCH_URL).mock(
        return_value=httpx.Response(200, json=EUROPEPMC_SEARCH_RESPONSE)
    )

    from integrations.europepmc import search_literature

    item = (await search_literature("TRPC5"))[0]

    assert item.open_access is None
    # The mocked record states only a publication year
    assert item.published_on == "2022"
    assert item.published_precision == "year"
    assert item.indexed_on is None


# ---------------------------------------------------------------------------
# ClinicalTrials.gov
# ---------------------------------------------------------------------------

CT_STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"

CT_RESPONSE = {
    "studies": [
        {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT04567890",
                    "briefTitle": "Phase 2 Study of Drug X in Alzheimer",
                },
                "statusModule": {"overallStatus": "RECRUITING"},
                "designModule": {
                    "studyType": "INTERVENTIONAL",
                    "phases": ["PHASE2"],
                },
                "conditionsModule": {"conditions": ["Alzheimer Disease"]},
                "armsInterventionsModule": {
                    "interventions": [{"name": "Drug X", "type": "DRUG"}]
                },
                "sponsorCollaboratorsModule": {
                    "leadSponsor": {"name": "Pharma Corp"}
                },
            }
        }
    ]
}


@pytest.mark.asyncio
@respx.mock
async def test_clinicaltrials_search():
    """Mock ClinicalTrials.gov v2 API JSON and assert ClinicalTrial fields."""
    respx.get(CT_STUDIES_URL).mock(
        return_value=httpx.Response(200, json=CT_RESPONSE)
    )

    from integrations.clinicaltrials import search_trials

    results = await search_trials("Alzheimer")

    assert len(results) == 1
    trial = results[0]
    assert trial.nct_id == "NCT04567890"
    assert trial.status == "Recruiting"
    assert trial.phase == "Phase 2"
    assert "Alzheimer Disease" in trial.conditions
    assert "Drug X" in trial.interventions
    assert trial.sponsor == "Pharma Corp"
    assert trial.url == "https://clinicaltrials.gov/study/NCT04567890"


@pytest.mark.asyncio
@respx.mock
async def test_clinicaltrials_known_status_labels():
    """Registry codes the frontend styles by name are mapped exactly."""
    respx.get(CT_STUDIES_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "studies": [
                    {
                        "protocolSection": {
                            "identificationModule": {"nctId": "NCT00000001"},
                            "statusModule": {
                                "overallStatus": "ACTIVE_NOT_RECRUITING"
                            },
                            "designModule": {"phases": ["EARLY_PHASE1", "NA"]},
                        }
                    }
                ]
            },
        )
    )

    from integrations.clinicaltrials import search_trials

    trial = (await search_trials("x"))[0]
    assert trial.status == "Active, not recruiting"
    assert trial.phase == "Early Phase 1, Not Applicable"


# ---------------------------------------------------------------------------
# openFDA
# ---------------------------------------------------------------------------

OPENFDA_LABEL_URL = "https://api.fda.gov/drug/label.json"

OPENFDA_LABEL_RESPONSE = {
    "results": [
        {
            "id": "fda-label-001",
            "openfda": {
                "brand_name": ["Testdrug"],
                "generic_name": ["testdrug"],
                "application_number": ["NDA012345"],
            },
            "indications_and_usage": ["Testdrug is indicated for treatment of condition X."],
            "warnings": ["Warnings Warnings Use with caution in renal impairment."],
        }
    ]
}


@pytest.mark.asyncio
@respx.mock
async def test_openfda_search():
    """Mock openFDA label JSON and assert EvidenceItem with source='openFDA'."""
    route = respx.get(OPENFDA_LABEL_URL).mock(
        return_value=httpx.Response(200, json=OPENFDA_LABEL_RESPONSE)
    )

    from integrations.openfda import search_drug_labels

    results = await search_drug_labels("Testdrug")

    # Should produce at least 2 items (indications + warnings)
    assert len(results) >= 2
    sources = {item.source for item in results}
    assert "openFDA" in sources
    evidence_types = {item.evidence_type.value for item in results}
    assert "regulatory" in evidence_types

    # openFDA parses '+' as a literal in its query syntax, so the boolean
    # operator must be sent as a plain space-separated OR.
    sent_search = route.calls[0].request.url.params["search"]
    assert "+OR+" not in sent_search
    assert sent_search == (
        'openfda.brand_name:"Testdrug" OR openfda.generic_name:"Testdrug"'
    )

    # Records are keyed by application number, which the API actually returns.
    assert all(item.id == "NDA012345" for item in results)

    # `?search=application_number:` 404s for every number this endpoint emits;
    # the indexed field is openfda.application_number.
    assert all(
        item.url
        == "https://api.fda.gov/drug/label.json?limit=1&search=openfda.application_number:%22NDA012345%22"
        for item in results
    )

    # Labelling text repeats its own section heading; the excerpt should not.
    warnings = next(i for i in results if i.metadata["section"] == "warnings")
    assert warnings.abstract == "Use with caution in renal impairment."


@pytest.mark.asyncio
@respx.mock
async def test_openfda_prefers_the_readable_label_link():
    """A label set id points at the rendered label, not at an API response."""
    respx.get(OPENFDA_LABEL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "openfda": {
                            "brand_name": ["Testdrug"],
                            "application_number": ["NDA012345"],
                            "spl_set_id": ["9a3d2f11-1111-41d2-b0aa-000011112222"],
                            "manufacturer_name": ["Packager LLC"],
                        },
                        "indications_and_usage": ["Testdrug is indicated for X."],
                    }
                ]
            },
        )
    )

    from integrations.openfda import search_drug_labels

    results = await search_drug_labels("Testdrug")
    assert results[0].url == (
        "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm"
        "?setid=9a3d2f11-1111-41d2-b0aa-000011112222"
    )
    assert results[0].metadata["label_manufacturer"] == "Packager LLC"


@pytest.mark.asyncio
@respx.mock
async def test_openfda_strips_quote_characters():
    """Unbalanced quotes would break openFDA's query syntax."""
    route = respx.get(OPENFDA_LABEL_URL).mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    from integrations.openfda import search_drug_labels

    await search_drug_labels('drug "x" \\ injection')

    sent_search = route.calls[0].request.url.params["search"]
    assert sent_search.count('"') == 4


# ---------------------------------------------------------------------------
# UniProt
# ---------------------------------------------------------------------------

UNIPROT_SEARCH_URL = "https://rest.uniprot.org/uniprotkb/search"

UNIPROT_SEARCH_RESPONSE = {
    "results": [
        {
            "primaryAccession": "Q9UL62",
            "proteinDescription": {
                "recommendedName": {
                    "fullName": {"value": "Short transient receptor potential channel 5"}
                }
            },
            "genes": [{"geneName": {"value": "TRPC5"}}],
            "organism": {
                "scientificName": "Homo sapiens",
                "commonName": "Human",
            },
            "comments": [
                {
                    "commentType": "FUNCTION",
                    "texts": [{"value": "Mediates calcium entry in neurons."}],
                },
                {
                    "commentType": "SUBCELLULAR LOCATION",
                    "subcellularLocations": [
                        {"location": {"value": "Cell membrane"}}
                    ],
                },
            ],
        }
    ]
}


@pytest.mark.asyncio
@respx.mock
async def test_uniprot_search():
    """Mock UniProt search JSON and assert TargetProfile fields."""
    respx.get(UNIPROT_SEARCH_URL).mock(
        return_value=httpx.Response(200, json=UNIPROT_SEARCH_RESPONSE)
    )

    from integrations.uniprot import search_target

    results = await search_target("TRPC5")

    assert len(results) == 1
    target = results[0]
    assert target.accession == "Q9UL62"
    assert target.gene == "TRPC5"
    assert target.organism == "Homo sapiens"
    assert target.function_summary == "Mediates calcium entry in neurons."
    assert target.subcellular_location == "Cell membrane"
    assert target.url == "https://www.uniprot.org/uniprotkb/Q9UL62"


@pytest.mark.asyncio
@respx.mock
async def test_uniprot_queries_gene_symbols_not_prose():
    """A multi-term research query is reduced to its gene symbol; UniProt scores prose poorly."""
    route = respx.get(UNIPROT_SEARCH_URL).mock(
        return_value=httpx.Response(200, json=UNIPROT_SEARCH_RESPONSE)
    )

    from integrations.uniprot import search_target

    await search_target("Clemizole and TRPC5 in Alzheimer's disease")

    sent = route.calls[0].request.url.params["query"]
    assert sent == '"TRPC5"'


@pytest.mark.asyncio
@respx.mock
async def test_uniprot_falls_back_to_whole_query():
    """With no gene-symbol-like token the query is sent verbatim, quoted as a phrase."""
    route = respx.get(UNIPROT_SEARCH_URL).mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    from integrations.uniprot import search_target

    assert await search_target("rezafungin antifungal resistance") == []
    assert route.calls[0].request.url.params["query"] == "rezafungin antifungal resistance"
