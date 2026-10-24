"""Date handling for retrieved literature records.

A source that states only a year is recorded as a year. Missing parts are left
missing rather than filled with a plausible-looking zero or the 1st of a month,
because the padding would read as precision the source never gave.
"""

from __future__ import annotations

import re
from typing import Optional


def precision_from_parts(
    year: Optional[int], month: Optional[int], day: Optional[int]
) -> tuple[Optional[str], Optional[str]]:
    """Return (ISO date, precision) from separately reported date parts."""
    if year is None:
        return None, None
    if month is None:
        return str(year), "year"
    if day is None:
        return f"{year:04d}-{month:02d}", "month"
    return f"{year:04d}-{month:02d}-{day:02d}", "day"


def normalize_date(raw: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Normalize a source date string to (ISO date, precision).

    Accepts ``2024-03-15``, ``20240315``, ``2024-03`` and ``2024``; anything that
    does not start with a four-digit year returns (None, None) so an unparsable
    string is never shown as a date.
    """
    if not raw:
        return None, None
    text = raw.strip()
    match = re.match(r"^(\d{4})(?:[-/]?(\d{2}))?(?:[-/]?(\d{2}))?", text)
    if not match:
        return None, None
    year = int(match.group(1))
    month = int(match.group(2)) if match.group(2) else None
    day = int(match.group(3)) if match.group(3) else None
    if month is not None and not 1 <= month <= 12:
        month = None
    if day is not None and not 1 <= day <= 31:
        day = None
    return precision_from_parts(year, month, day)


def sort_key(published_on: Optional[str], year: Optional[int] = None) -> tuple[int, int, int]:
    """A comparable (year, month, day) for a date the source may state partly.

    Sorting needs one number per record, so a year-only date sorts at the start
    of that year and a month-only date at the start of that month. The padding is
    used for ordering only and is never displayed as a date.
    """
    iso, _ = normalize_date(published_on)
    if iso is None:
        if year is None:
            return (0, 0, 0)
        return (year, 1, 1)
    parts = [int(p) for p in iso.split("-")]
    while len(parts) < 3:
        parts.append(1)
    return (parts[0], parts[1], parts[2])
