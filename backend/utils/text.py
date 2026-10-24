"""MolTel — text utility functions."""

from __future__ import annotations

import re
from typing import Optional


def truncate(text: str, max_chars: int = 500) -> str:
    """Truncate text to max_chars, appending ellipsis when truncated."""
    if not text:
        return text
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


def clean_whitespace(text: str) -> str:
    """Collapse multiple whitespace characters into a single space."""
    if not text:
        return text
    return re.sub(r"\s+", " ", text).strip()


def condense(text: str, max_chars: int = 320) -> str:
    """Shorten text to whole sentences that fit max_chars, falling back to truncation."""
    if not text:
        return text
    text = clean_whitespace(text)
    if len(text) <= max_chars:
        return text

    kept: list[str] = []
    used = 0
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if kept and used + len(sentence) + 1 > max_chars:
            break
        kept.append(sentence)
        used += len(sentence) + 1
        if used >= max_chars:
            break

    if len(kept) <= 1 and used > max_chars:
        return truncate(text, max_chars)
    return " ".join(kept)


def extract_year(date_str: Optional[str]) -> Optional[int]:
    """Extract a 4-digit year from a date string (YYYY-MM-DD or YYYY)."""
    if not date_str:
        return None
    match = re.search(r"\b(\d{4})\b", date_str)
    if match:
        year = int(match.group(1))
        if 1900 <= year <= 2100:
            return year
    return None


def normalize_doi(doi_str: Optional[str]) -> Optional[str]:
    """Strip URL prefixes from a DOI, returning the bare DOI (10.xxxx/...)."""
    if not doi_str:
        return None
    doi_str = doi_str.strip()
    # Remove common URL prefixes
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi:",
        "DOI:",
    ):
        if doi_str.startswith(prefix):
            doi_str = doi_str[len(prefix):]
            break
    doi_str = doi_str.strip()
    # Must start with 10. to be a valid DOI
    if doi_str.startswith("10."):
        return doi_str
    return None


def normalize_pmcid(pmcid_str: Optional[str]) -> Optional[str]:
    """Return a PMCID as ``PMC`` plus its digits, so either source's form keys.

    PubMed's article-id list and EuropePMC name the same record "1234567" and
    "PMC1234567"; a bare number is prefixed rather than treated as a different id.
    """
    if not pmcid_str:
        return None
    text = pmcid_str.strip().upper()
    if text.startswith("PMC"):
        text = text[3:]
    digits = re.match(r"^\d+", text)
    if not digits:
        return None
    return f"PMC{digits.group(0)}"

