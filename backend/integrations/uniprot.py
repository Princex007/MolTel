"""UniProt REST API integration."""

from __future__ import annotations

import logging
import re
from typing import Optional

from models.schemas import TargetProfile
from utils.http import safe_get

logger = logging.getLogger(__name__)

BASE_URL = "https://rest.uniprot.org/uniprotkb"

_FIELDS = (
    "accession,protein_name,gene_names,organism_name,"
    "cc_function,cc_subcellular_location"
)

# UniProt scores long prose poorly and returns unrelated proteins for it, so a
# research query is reduced to its gene-symbol-like tokens before searching.
_GENE_SYMBOL = re.compile(r"\b[A-Z][A-Z0-9]{1,9}\b")


def _candidate_terms(query: str) -> list[str]:
    """Terms worth querying UniProt with, most specific first."""
    symbols = [t for t in _GENE_SYMBOL.findall(query) if t != query.upper()]
    if symbols:
        # Deduplicate while preserving order
        return list(dict.fromkeys(symbols))
    return [query]


async def search_target(query: str, max_results: int = 3) -> list[TargetProfile]:
    """Search UniProt for protein targets matching the query."""
    url = f"{BASE_URL}/search"
    targets: list[TargetProfile] = []
    seen: set[str] = set()

    for term in _candidate_terms(query):
        params = {
            "query": f'"{term}"' if " " not in term else term,
            "format": "json",
            "size": str(max_results),
            "fields": _FIELDS,
        }
        data = await safe_get(url, params=params)
        if data is None:
            continue
        for entry in data.get("results", []):
            target = _parse_entry(entry)
            if target and target.accession not in seen:
                seen.add(target.accession)
                targets.append(target)
        if len(targets) >= max_results:
            break

    return targets[:max_results]


def _parse_entry(entry: dict) -> Optional[TargetProfile]:
    """Parse a single UniProt entry into a TargetProfile."""
    try:
        accession: str = entry.get("primaryAccession", "")
        if not accession:
            return None

        # Protein name
        protein_desc = entry.get("proteinDescription", {})
        rec_name = protein_desc.get("recommendedName", {})
        full_name_obj = rec_name.get("fullName", {})
        name: Optional[str] = full_name_obj.get("value") if full_name_obj else None

        # Gene names
        gene_names_list = entry.get("genes", [])
        gene: Optional[str] = None
        if gene_names_list:
            gn = gene_names_list[0].get("geneName", {})
            gene = gn.get("value") if gn else None

        # Organism
        organism_obj = entry.get("organism", {})
        organism_names = organism_obj.get("scientificName")
        if not organism_names:
            common = organism_obj.get("commonName")
            organism_names = common
        organism = organism_names

        # Function (from cc_function comments)
        function_summary = _extract_comment(entry, "FUNCTION")

        # Subcellular location
        subcellular_location = _extract_comment(entry, "SUBCELLULAR LOCATION")

        url = f"https://www.uniprot.org/uniprotkb/{accession}"

        return TargetProfile(
            accession=accession,
            name=name,
            gene=gene,
            organism=organism,
            function_summary=function_summary,
            subcellular_location=subcellular_location,
            url=url,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("UniProt: error parsing entry: %s", exc)
        return None


def _extract_comment(entry: dict, comment_type: str) -> Optional[str]:
    """Extract text from a specific comment type in a UniProt entry."""
    comments = entry.get("comments", [])
    for comment in comments:
        if comment.get("commentType", "").upper() == comment_type.upper():
            # Function comments have texts list
            texts = comment.get("texts", [])
            if texts:
                return texts[0].get("value")
            # Subcellular location has locations list
            locations = comment.get("subcellularLocations", [])
            if locations:
                location_names = []
                for loc in locations:
                    loc_name = loc.get("location", {}).get("value")
                    if loc_name:
                        location_names.append(loc_name)
                return ", ".join(location_names) if location_names else None
    return None
