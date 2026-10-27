"""Core data models."""

from __future__ import annotations

import hashlib
import re
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import Optional

from pydantic import BaseModel, Field

# Categories a job can be classified into (set during filtering).
Category = str  # one of: "swe", "quant", "consulting", "other"


def normalize_title(title: str) -> str:
    """Lowercase + collapse whitespace, for stable IDs and matching."""
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def normalize_company(company: str) -> str:
    """Lowercase + collapse whitespace for stable IDs."""
    return re.sub(r"\s+", " ", (company or "").strip().lower())


_TRACKING_PARAM_EXACT = {
    "fbclid",
    "gclid",
    "mkt_tok",
    "mc_cid",
    "mc_eid",
}
_TRACKING_PARAM_PREFIXES = ("utm_",)


def normalize_url(url: str) -> str:
    """Drop fragments and common tracking params from a URL."""
    raw = (url or "").strip()
    if not raw:
        return ""

    parsed = urlsplit(raw)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_PARAM_EXACT
        and not key.lower().startswith(_TRACKING_PARAM_PREFIXES)
    ]
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path,
            urlencode(query, doseq=True),
            "",
        )
    )


class Job(BaseModel):
    """A normalized job posting from any source."""

    company: str
    title: str
    url: str
    locations: list[str] = Field(default_factory=list)
    source: str = ""  # e.g. "simplify-summer", "greenhouse:Stripe"
    ats: Optional[str] = None  # greenhouse | lever | ashby | workday | github-list

    # Filled in by the filter step.
    category: Optional[Category] = None
    season: Optional[str] = None  # summer | spring | fall | winter | offcycle
    year: Optional[int] = None

    # Optional metadata when the source provides it.
    posted_date: Optional[str] = None  # ISO date string when known
    sponsorship: Optional[str] = None
    active: bool = True
    # Set when `url` was resolved from a link shortener; holds the short link.
    short_url: Optional[str] = None

    @property
    def location_str(self) -> str:
        return " | ".join(self.locations) if self.locations else ""

    @property
    def job_id(self) -> str:
        """Legacy id used by the apply log and old seen-job state."""
        basis = f"{self.company.strip().lower()}|{normalize_title(self.title)}|{self.url.strip()}"
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]

    @property
    def dedup_id(self) -> str:
        """Newsletter dedup id based on normalized company/title/url."""
        basis = "|".join(
            [
                normalize_company(self.company),
                normalize_title(self.title),
                normalize_url(self.url),
            ]
        )
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


class ApplicantProfile(BaseModel):
    """Stored applicant info for the (future) auto-apply module.

    Loaded from config/profile.yaml (gitignored if it holds real data).
    Nothing here is used by the notify pipeline today — it exists so the
    auto-apply module has a stable contract to build against.
    """

    full_name: str = ""
    email: str = ""
    phone: str = ""
    school: str = ""
    graduation_date: str = ""  # e.g. "2027-05"
    gpa: str = ""
    current_location: str = ""  # e.g. "Boston, MA"
    work_authorization: str = ""  # e.g. "US Citizen", "Need sponsorship"
    requires_sponsorship: Optional[bool] = None
    linkedin: str = ""
    github: str = ""
    website: str = ""
    resume_path: str = ""  # local path to resume PDF (gitignored)
    # A few sentences about your background/skills — used to ground the
    # AI-generated cover letter so it reflects real experience, not invention.
    summary: str = ""
    # Common screening questions -> canned answers, e.g.
    #   {"Are you authorized to work in the US?": "Yes"}
    common_answers: dict[str, str] = Field(default_factory=dict)

    @property
    def is_configured(self) -> bool:
        """Minimum needed to attempt an application."""
        return bool(self.full_name and self.email and self.resume_path)
