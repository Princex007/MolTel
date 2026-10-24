"""openFDA drug label API integration.

NOTE: Adverse events reported to openFDA are not proof of causality.
They represent spontaneous reports and should be interpreted accordingly.
"""

from __future__ import annotations

import logging
import re

from models.schemas import EvidenceItem, EvidenceType
from utils.http import safe_get
from utils.text import clean_whitespace, condense, truncate

logger = logging.getLogger(__name__)

BASE_URL = "https://api.fda.gov/drug"

# Identifiers are interpolated into a link, so only a plain id is allowed in.
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


def _strip_repeated_heading(content: str, section_title: str) -> str:
    """Drop the section title where labelling text repeats it before the body."""
    heading = re.escape(section_title)
    stripped = re.sub(rf"^(?:\s*{heading}\s*[:\-–—]?\s*)+", "", content, flags=re.IGNORECASE)
    return stripped.strip() or content.strip()

# Label sections to extract and their human-readable names
_LABEL_SECTIONS = [
    ("indications_and_usage", "Indications and Usage"),
    ("warnings", "Warnings"),
    ("contraindications", "Contraindications"),
    ("adverse_reactions", "Adverse Reactions"),
    ("drug_interactions", "Drug Interactions"),
]


async def search_drug_labels(query: str) -> list[EvidenceItem]:
    """Search openFDA drug labels and return EvidenceItems for each section found."""
    url = f"{BASE_URL}/label.json"
    # openFDA rejects unbalanced quotes; keep the term safe for its query syntax.
    term = query.replace('"', " ").replace("\\", " ").strip()
    if not term:
        return []
    params = {
        "search": (
            f'openfda.brand_name:"{term}" OR openfda.generic_name:"{term}"'
        ),
        "limit": "3",
    }
    data = await safe_get(url, params=params)
    if data is None:
        return []

    results = data.get("results", [])
    items: list[EvidenceItem] = []

    for label in results:
        # Extract the drug name for display
        openfda = label.get("openfda", {})
        brand_names = openfda.get("brand_name", [])
        generic_names = openfda.get("generic_name", [])
        drug_name = brand_names[0] if brand_names else (generic_names[0] if generic_names else query)
        application_number = (
            label.get("application_number")
            or (openfda.get("application_number") or [None])[0]
        )
        # The manufacturer/packager printed on the label. `drug/label.json` does
        # not return an application holder (there is no openfda.sponsor_name
        # field: a select on it is rejected), so this is recorded as exactly
        # what it is and never promoted to "developer" or "marketing
        # authorization holder".
        label_manufacturer = (openfda.get("manufacturer_name") or [None])[0]
        # DailyMed's id for this exact label document — the readable version of
        # the record the quoted passage came from.
        spl_set_id = (openfda.get("spl_set_id") or [None])[0]

        for field, section_title in _LABEL_SECTIONS:
            content_list = label.get(field, [])
            if not content_list:
                continue
            # Each field is a list of strings; join and truncate
            content = _strip_repeated_heading(
                " ".join(content_list), section_title
            )
            content = truncate(condense(clean_whitespace(content), 700), 1000)

            items.append(
                EvidenceItem(
                    source="openFDA",
                    source_type="regulatory",
                    id=application_number,
                    title=f"{drug_name} — {section_title}",
                    year=None,
                    authors=[],
                    abstract=content,
                    url=_record_url(application_number, spl_set_id),
                    evidence_type=EvidenceType.regulatory,
                    metadata={
                        "section": field,
                        "section_title": section_title,
                        "drug_name": drug_name,
                        "application_number": application_number,
                        "label_manufacturer": label_manufacturer,
                        "generic_names": generic_names,
                        "brand_names": brand_names,
                    },
                )
            )

    return items


def _record_url(application_number: str | None, spl_set_id: str | None) -> str | None:
    """Link back to the label so every claim stays verifiable.

    `?search=application_number:` is not an indexed field on this endpoint and
    returns 404 for every number, so the label's DailyMed set id is used when
    openFDA supplies one; the searchable `openfda.application_number` is the
    fallback.
    """
    if spl_set_id and _SAFE_ID.fullmatch(spl_set_id):
        return f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={spl_set_id}"
    if application_number and _SAFE_ID.fullmatch(application_number):
        return (
            "https://api.fda.gov/drug/label.json?limit=1&search="
            f"openfda.application_number:%22{application_number}%22"
        )
    return "https://open.fda.gov/apis/drug/label/"
