"""PubChem PUG REST API integration."""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import quote

import httpx

from models.schemas import CompoundProfile
from utils.http import get_async_client

logger = logging.getLogger(__name__)

BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"

_PROPERTIES = (
    "MolecularFormula,MolecularWeight,ConnectivitySMILES,SMILES,"
    "IUPACName,InChIKey"
)


async def search_compound(name: str) -> Optional[CompoundProfile]:
    """Search PubChem for a compound by name and return a CompoundProfile."""
    url = f"{BASE_URL}/compound/name/{quote(name, safe='')}/property/{_PROPERTIES}/JSON"
    try:
        async with get_async_client() as client:
            response = await client.get(url)
            if response.status_code == 404:
                logger.info("PubChem: compound '%s' not found", name)
                return None
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException:
        logger.warning("PubChem: timeout searching for '%s'", name)
        return None
    except httpx.HTTPStatusError as exc:
        logger.warning("PubChem: HTTP %s for '%s'", exc.response.status_code, name)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("PubChem: unexpected error for '%s': %s", name, exc)
        return None

    props_list = data.get("PropertyTable", {}).get("Properties", [])
    if not props_list:
        return None

    props = props_list[0]
    cid = str(props.get("CID", ""))

    # Fetch synonyms in a second request
    synonyms: list[str] = []
    if cid:
        synonyms = await _fetch_synonyms(cid=cid)

    return CompoundProfile(
        cid=cid,
        name=name,
        synonyms=synonyms,
        molecular_formula=props.get("MolecularFormula"),
        molecular_weight=str(props["MolecularWeight"]) if props.get("MolecularWeight") else None,
        canonical_smiles=props.get("ConnectivitySMILES") or props.get("CanonicalSMILES"),
        isomeric_smiles=props.get("SMILES") or props.get("IsomericSMILES"),
        iupac_name=props.get("IUPACName"),
        inchi_key=props.get("InChIKey"),
    )


async def _fetch_synonyms(cid: str) -> list[str]:
    """Fetch synonyms for a CID from PubChem."""
    url = f"{BASE_URL}/compound/cid/{cid}/synonyms/JSON"
    try:
        async with get_async_client() as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("PubChem: could not fetch synonyms for CID %s: %s", cid, exc)
        return []

    info_list = data.get("InformationList", {}).get("Information", [])
    if not info_list:
        return []
    return info_list[0].get("Synonym", [])[:20]  # cap at 20 synonyms
