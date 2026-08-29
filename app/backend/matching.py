"""Normalization and three-level matching for agent lookups."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlparse


def _to_half_width(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def normalize_text(value: str | None) -> str | None:
    """Trim, collapse spaces, and unify case and width. None stays None."""

    if value is None:
        return None
    collapsed = re.sub(r"\s+", " ", _to_half_width(value)).strip()
    if not collapsed:
        return None
    return collapsed.casefold()


def normalize_url(value: str | None) -> str | None:
    """Keep only scheme, host and path; drop auth, query, fragment, trailing slash."""

    if value is None:
        return None
    candidate = _to_half_width(value).strip()
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    try:
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        return None
    if not host:
        return None
    if port:
        host = f"{host}:{port}"
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{host}{path}".casefold()


@dataclass
class MatchQuery:
    """Fields used to find a record; every field is optional."""

    application_id: int | None = None
    company_name: str | None = None
    job_title: str | None = None
    job_code: str | None = None
    location: str | None = None
    job_url: str | None = None

    @classmethod
    def from_fields(cls, fields: dict[str, object]) -> "MatchQuery":
        return cls(
            application_id=fields.get("application_id"),
            company_name=fields.get("company_name"),
            job_title=fields.get("job_title"),
            job_code=fields.get("job_code"),
            location=fields.get("location"),
            job_url=fields.get("job_url"),
        )

    def has_any(self) -> bool:
        if self.application_id is not None:
            return True
        values = (self.company_name, self.job_title, self.job_code, self.location, self.job_url)
        return any(value is not None and str(value).strip() for value in values)


def active_rows(connection) -> list[dict]:
    return [dict(row) for row in connection.execute(
        "SELECT * FROM applications WHERE archived_at IS NULL"
    ).fetchall()]


def find_matching(connection, query: MatchQuery) -> list[dict]:
    """Return the uniquely matched active record for the query.

    Priority: exact active application ID, normalized job_url, company +
    job_code, then company + job_title + location. Once a level finds one or
    more candidates, lower-priority fields are not used to change that result.
    """

    rows = active_rows(connection)

    if query.application_id is not None:
        return [row for row in rows if row["id"] == query.application_id]

    norm_url = normalize_url(query.job_url)
    if norm_url:
        matches = [row for row in rows if normalize_url(row["job_url"]) == norm_url]
        if matches:
            return matches

    norm_company = normalize_text(query.company_name)
    norm_code = normalize_text(query.job_code)
    if norm_company and norm_code:
        matches = [
            row for row in rows
            if normalize_text(row["company_name"]) == norm_company
            and normalize_text(row["job_code"]) == norm_code
        ]
        if matches:
            return matches

    norm_title = normalize_text(query.job_title)
    norm_location = normalize_text(query.location)
    if norm_company and norm_title and norm_location:
        matches = [
            row for row in rows
            if normalize_text(row["company_name"]) == norm_company
            and normalize_text(row["job_title"]) == norm_title
            and normalize_text(row["location"]) == norm_location
        ]
        return matches

    return []
