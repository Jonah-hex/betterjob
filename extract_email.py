"""Extract contact emails from company websites."""

from __future__ import annotations

import re
import time
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import httpx
import yaml
from bs4 import BeautifulSoup

import database as db

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
SKIP_DOMAINS = {"example.com", "sentry.io", "wixpress.com", "google.com", "facebook.com"}
USER_AGENT = "BetterJob-Outreach/1.0 (+job-application; contact-page-only)"


def load_config(path: str = "config.yaml") -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _normalize_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/")


def _extract_domain(url: str) -> str:
    return urlparse(url).netloc.replace("www.", "")


def _score_email(email: str, priority_prefixes: list[str]) -> int:
    local = email.split("@")[0].lower()
    for i, prefix in enumerate(priority_prefixes):
        if local.startswith(prefix):
            return 100 - i
    return 0


def _find_emails_in_html(html: str) -> set[str]:
    emails: set[str] = set()
    soup = BeautifulSoup(html, "html.parser")

    for a in soup.select('a[href^="mailto:"]'):
        href = a.get("href", "")
        addr = href.replace("mailto:", "").split("?")[0].strip()
        if EMAIL_RE.fullmatch(addr):
            emails.add(addr.lower())

    for match in EMAIL_RE.findall(html):
        domain = match.split("@")[1].lower()
        if domain not in SKIP_DOMAINS:
            emails.add(match.lower())

    return emails


def fetch_page(url: str, timeout: int = 15) -> Optional[str]:
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = client.get(url)
            if response.status_code >= 400:
                return None
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type and "text/" not in content_type:
                return None
            return response.text
    except httpx.HTTPError:
        return None


def extract_from_website(
    website: str,
    config: Optional[dict[str, Any]] = None,
) -> list[dict[str, str]]:
    config = config or load_config()
    ext_cfg = config.get("email_extraction", {})
    paths = ext_cfg.get("paths_to_try", ["/contact"])
    delay = ext_cfg.get("request_delay_seconds", 2)
    timeout = ext_cfg.get("timeout_seconds", 15)
    priority = ext_cfg.get("priority_prefixes", ["careers", "hr"])
    allow_guessed = ext_cfg.get("allow_guessed_emails", False)

    base = _normalize_url(website)
    domain = _extract_domain(base)
    found: dict[str, str] = {}

    urls_to_try = [base] + [urljoin(base + "/", p.lstrip("/")) for p in paths]

    for url in urls_to_try:
        html = fetch_page(url, timeout)
        if html:
            for email in _find_emails_in_html(html):
                email_domain = email.split("@")[1]
                if domain in email_domain or email_domain.endswith("." + domain):
                    found[email] = "found_on_page"
        time.sleep(delay)

    if not found and allow_guessed:
        for prefix in priority:
            guessed = f"{prefix}@{domain}"
            found[guessed] = "guessed"

    ranked = sorted(
        found.items(),
        key=lambda x: _score_email(x[0], priority),
        reverse=True,
    )
    return [{"email": e, "source": s} for e, s in ranked]


def extract_for_company(company_id: int, config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    config = config or load_config()
    company = db.get_company(company_id)
    if not company:
        return {"status": "error", "message": "Company not found"}

    website = company.get("website")
    if not website:
        db.update_company_status(company_id, "no_email")
        return {"status": "no_email", "message": "No website"}

    results = extract_from_website(website, config)
    sendable = [r for r in results if r["source"] != "guessed"]

    if not sendable:
        db.update_company_status(company_id, "no_email")
        return {"status": "no_email", "emails": results}

    for i, item in enumerate(sendable):
        db.add_email(
            company_id=company_id,
            email=item["email"],
            source=item["source"],
            is_primary=(i == 0),
            verified=item["source"] == "found_on_page",
        )

    db.update_company_status(company_id, "email_found")
    return {"status": "email_found", "emails": sendable}


def extract_all_pending(config: Optional[dict[str, Any]] = None) -> dict[str, int]:
    config = config or load_config()
    companies = db.get_companies_without_email()
    stats = {"processed": 0, "email_found": 0, "no_email": 0, "errors": 0}

    for company in companies:
        try:
            result = extract_for_company(company["id"], config)
            stats["processed"] += 1
            if result["status"] == "email_found":
                stats["email_found"] += 1
            elif result["status"] == "no_email":
                stats["no_email"] += 1
        except Exception:
            stats["errors"] += 1

    return stats


def extract_for_companies(company_ids: list[int], config: Optional[dict[str, Any]] = None) -> dict[str, int]:
    stats = {"processed": 0, "email_found": 0, "no_email": 0, "errors": 0}
    for cid in company_ids:
        try:
            result = extract_for_company(cid, config)
            stats["processed"] += 1
            if result["status"] == "email_found":
                stats["email_found"] += 1
            elif result["status"] == "no_email":
                stats["no_email"] += 1
        except Exception:
            stats["errors"] += 1
    return stats
