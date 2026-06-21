"""Job-fit scoring for companies against surveyor profile."""

from __future__ import annotations

import re
from typing import Any, Optional


SURVEYOR_KEYWORDS = (
    "survey", "surveyor", "surveying", "مساح", "مساحة", "topographic",
    "total station", "gnss", "rtk", "setting out", "as-built",
    "construction survey", "land survey", "geomatics", "gis",
)

ENGINEERING_KEYWORDS = (
    "engineering", "engineer", "consultant", "هندس", "استشارات",
    "civil", "infrastructure", "مقاول", "contractor", "construction",
)

HR_SIGNALS = ("hr@", "careers@", "recruitment@", "jobs@", "توظيف", "careers", "jobs")


def score_company(company: dict[str, Any], config: Optional[dict[str, Any]] = None) -> int:
    """0-100 fit score for General Land Surveyor outreach."""
    config = config or {}
    profile = config.get("profile", {})
    text = " ".join(
        str(company.get(k, "") or "")
        for k in ("company_name", "sector", "website", "notes", "city", "primary_email", "email")
    ).lower()

    score = 0

    for kw in SURVEYOR_KEYWORDS:
        if kw in text:
            score += 12
    for kw in ENGINEERING_KEYWORDS:
        if kw in text:
            score += 6

    sector = (company.get("sector") or "").lower()
    if sector in ("surveying", "survey", "مساحة"):
        score += 25
    elif sector in ("engineering", "construction"):
        score += 15

    email = (company.get("primary_email") or company.get("email") or "").lower()
    email_source = (company.get("email_source") or company.get("source") or "").lower()
    if email:
        local = email.split("@")[0]
        if any(local == p or local.startswith(f"{p}.") for p in ("hr", "careers", "recruitment", "jobs")):
            score += 20
        elif email_source in ("found_on_page", "manual", "csv", "google_places"):
            score += 12
        elif email_source in ("domain_pattern", "directory") and local in ("info", "contact", "admin"):
            score -= 25
        else:
            score += 5

    if company.get("website"):
        score += 8
    if company.get("phone"):
        score += 5

    src = (company.get("discovery_source") or "").lower()
    if src in ("linkedin", "careers_portal", "deep_search"):
        score += 10

    cities = config.get("automation", {}).get("target_cities", [])
    if company.get("city") in cities:
        score += 5

    if profile.get("city", "").lower() in text:
        score += 3

    return min(100, score)


def rank_companies(companies: list[dict[str, Any]], config: Optional[dict] = None) -> list[dict[str, Any]]:
    ranked = []
    for c in companies:
        row = dict(c)
        row["job_fit_score"] = score_company(c, config)
        ranked.append(row)
    return sorted(ranked, key=lambda x: x.get("job_fit_score", 0), reverse=True)


def sync_all_scores(config: Optional[dict] = None) -> int:
    """Persist job_fit_score for all companies in DB."""
    import database as db

    config = config or {}
    companies = db.get_companies()
    count = 0
    for c in companies:
        score = score_company(c, config)
        db.update_company_job_fit(c["id"], score)
        count += 1
    return count


def fit_label(score: int) -> str:
    if score >= 75:
        return "ممتاز"
    if score >= 50:
        return "جيد"
    if score >= 30:
        return "متوسط"
    return "ضعيف"
