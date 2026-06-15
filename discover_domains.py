"""Enrich companies with domain-based contact emails from their websites."""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlparse

import yaml

import database as db

PRIORITY_PREFIXES = ("hr", "careers", "jobs", "recruitment", "info", "contact")


def load_config(path: str = "config.yaml") -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _extract_domain(website: str) -> Optional[str]:
    if not website:
        return None
    if not website.startswith("http"):
        website = "https://" + website
    host = urlparse(website).netloc.lower().replace("www.", "")
    if not host or "." not in host:
        return None
    if any(skip in host for skip in ("facebook.com", "instagram.com", "linkedin.com")):
        return None
    return host


def _is_sa_domain(domain: str) -> bool:
    return domain.endswith(".sa") or domain.endswith(".com.sa")


def enrich_company_domains(
    company_id: int,
    config: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Add domain-pattern email if company has website but no email yet."""
    config = config or load_config()
    if not config.get("discovery", {}).get("allow_domain_emails", True):
        return None

    company = db.get_company(company_id)
    if not company or company.get("status") not in ("discovered", "no_email"):
        return None
    if db.get_primary_email(company_id):
        return None

    domain = _extract_domain(company.get("website", ""))
    if not domain:
        return None

    prefixes = config.get("email_extraction", {}).get("priority_prefixes", list(PRIORITY_PREFIXES))
    for prefix in prefixes:
        email = f"{prefix}@{domain}"
        if not re.fullmatch(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", email):
            continue
        if db.add_email(company_id, email, "domain_pattern", is_primary=True, verified=False):
            db.update_company_status(company_id, "email_found")
            return email
    return None


def enrich_all_pending(config: Optional[dict[str, Any]] = None) -> dict[str, int]:
    config = config or load_config()
    companies = db.get_companies_without_email()
    stats = {"processed": 0, "email_found": 0, "skipped": 0}

    for company in companies:
        stats["processed"] += 1
        email = enrich_company_domains(company["id"], config)
        if email:
            stats["email_found"] += 1
        else:
            stats["skipped"] += 1

    return stats
