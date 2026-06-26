"""Deep job & company discovery — LinkedIn, careers portals, HR-focused web search."""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any, Optional
from urllib.parse import urlparse

import yaml

import database as db
import outreach_quality
from discover_directory import (
    CITY_QUERIES,
    _clean_name,
    _host_ok,
    _infer_sector,
    _matches_filters,
    _normalize_url,
    _place_id,
    _search_duckduckgo,
)

LINKEDIN_JOB_QUERIES = [
    'site:linkedin.com/jobs "land surveyor" Saudi Arabia',
    'site:linkedin.com/jobs "surveyor" Jeddah',
    'site:linkedin.com/jobs "مساح" السعودية',
    'site:linkedin.com/jobs "total station" Saudi',
    'site:linkedin.com/jobs "construction surveyor" Jeddah',
    'site:linkedin.com/company construction Jeddah Saudi',
    'site:linkedin.com/company "land surveying" Saudi Arabia',
    'site:linkedin.com/company engineering consultant Jeddah',
]

CAREERS_PORTAL_QUERIES = [
    'site:careers-ksa.com مساح',
    'site:careers-ksa.com surveyor',
    'site:careers-ksa.com هندسة مدنية جدة',
    'site:bayt.com مساح جدة',
    'site:bayt.com land surveyor Saudi Arabia',
    'site:sa.indeed.com surveyor Jeddah',
    'site:glassdoor.com land surveyor Saudi Arabia',
    'site:naukrigulf.com surveyor Saudi',
    'site:gulftalent.com land surveyor',
    'site:tanqeeb.com مساح السعودية',
]

HR_EMAIL_QUERIES = [
    '"hr@" "construction" jeddah saudi',
    '"careers@" engineering company jeddah',
    '"recruitment@" مقاولات جدة',
    'site:.sa "careers@" surveyor OR مساح',
    'شركة مقاولات جدة "توظيف" email',
    'engineering consultant abha "hr@" OR "careers@"',
    'land surveying company saudi "contact" email',
]

EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+-]+@(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}",
    re.I,
)

HR_PREFIXES = ("hr", "careers", "recruitment", "jobs", "hiring", "talent")


def load_config(path: str = "config.yaml") -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _merge_queries(*lists: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for lst in lists:
        for query in lst:
            q = query.strip()
            if q and q not in seen:
                seen.add(q)
                merged.append(q)
    return merged


def _queries_from_job_titles(
    config: dict[str, Any],
    platform: str,
    city: str,
) -> list[str]:
    """Build search queries from ranked target_job_titles in config."""
    titles = config.get("job_discovery", {}).get("target_job_titles", [])
    queries: list[str] = []
    for item in titles:
        for kw in item.get("keywords_en", []):
            kw = str(kw).strip()
            if not kw:
                continue
            if platform == "linkedin":
                queries.append(f'site:linkedin.com/jobs "{kw}" {city}')
            elif platform == "careers":
                queries.append(f"site:bayt.com {kw} {city}")
                queries.append(f"site:careers-ksa.com {kw}")
        for kw in item.get("keywords_ar", []):
            kw = str(kw).strip()
            if not kw:
                continue
            if platform == "linkedin":
                queries.append(f'site:linkedin.com/jobs "{kw}" {city}')
            elif platform == "careers":
                queries.append(f"site:tanqeeb.com {kw} السعودية")
    return queries


def _city_queries(config: dict[str, Any]) -> dict[str, list[str]]:
    """Merge config job_discovery queries with defaults."""
    base = dict(CITY_QUERIES)
    jd = config.get("job_discovery", {})
    for city in config.get("automation", {}).get("target_cities", []):
        extra = jd.get("extra_queries", {}).get(city, [])
        if extra:
            base.setdefault(city, [])
            base[city].extend(extra)
    return base


def _employer_queries(config: dict[str, Any], city: str = "Jeddah") -> list[str]:
    queries: list[str] = []
    for emp in config.get("job_discovery", {}).get("priority_employers", []):
        for query in emp.get("search_queries", []):
            q = str(query).replace("{city}", city)
            queries.append(q)
    return queries


def _linkedin_queries(config: dict[str, Any], city: str) -> list[str]:
    jd = config.get("job_discovery", {})
    city_queries = [q.replace("Jeddah", city) for q in LINKEDIN_JOB_QUERIES]
    if city != "Jeddah":
        city_queries = [q.replace("jeddah", city.lower()) for q in city_queries]
    return _merge_queries(
        city_queries,
        [q.replace("Jeddah", city) for q in jd.get("linkedin_queries", [])],
        _queries_from_job_titles(config, "linkedin", city),
        _employer_queries(config, city),
    )


def _careers_queries(config: dict[str, Any], city: str) -> list[str]:
    jd = config.get("job_discovery", {})
    portal_queries = list(CAREERS_PORTAL_QUERIES)
    if city == "Abha":
        portal_queries = [
            q.replace("jeddah", "abha").replace("Jeddah", "Abha")
            for q in portal_queries
        ]
    config_queries = jd.get("careers_queries", [])
    if city == "Abha":
        config_queries = [
            q.replace("jeddah", "abha").replace("Jeddah", "Abha")
            for q in config_queries
        ]
    return _merge_queries(
        portal_queries,
        config_queries,
        _queries_from_job_titles(config, "careers", city),
        _employer_queries(config, city),
    )


def _extract_emails_from_page(url: str, timeout: int = 12) -> list[str]:
    import httpx
    from bs4 import BeautifulSoup

    emails: list[str] = []
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "BetterJob-Outreach/1.0"})
            if resp.status_code >= 400:
                return emails
            text = resp.text
    except Exception:
        return emails

    for match in EMAIL_RE.findall(text):
        em = match.lower()
        if any(skip in em for skip in ("example.com", "wixpress", "sentry", "png")):
            continue
        emails.append(em)

    soup = BeautifulSoup(text, "html.parser")
    for a in soup.select('a[href^="mailto:"]'):
        href = a.get("href", "").replace("mailto:", "").split("?")[0].strip()
        if "@" in href:
            emails.append(href.lower())

    seen: set[str] = set()
    ordered: list[str] = []
    for em in emails:
        if em not in seen:
            seen.add(em)
            ordered.append(em)
    return ordered


def _pick_hr_email(emails: list[str]) -> Optional[str]:
    for em in emails:
        local = em.split("@")[0]
        if any(local.startswith(p) or local == p for p in HR_PREFIXES):
            return em
    return emails[0] if emails else None


def _upsert_candidate(
    name: str,
    website: Optional[str],
    city: str,
    region_key: str,
    source: str,
    config: dict[str, Any],
    linkedin_url: Optional[str] = None,
    careers_url: Optional[str] = None,
    job_url: Optional[str] = None,
    phone: Optional[str] = None,
    stats: Optional[dict[str, int]] = None,
) -> None:
    stats = stats or {"new": 0, "updated": 0, "skipped": 0}
    name = _clean_name(name)
    if not name or len(name) < 3:
        stats["skipped"] += 1
        return
    if not _matches_filters(name, config):
        stats["skipped"] += 1
        return
    if outreach_quality.is_excluded_company(
        name, website, job_url or careers_url or linkedin_url, config
    ):
        stats["skipped"] += 1
        return

    place_id = _place_id(source, name, website or linkedin_url or job_url or city)
    sector = _infer_sector(name, website or linkedin_url or "")

    company_id, is_new = db.upsert_company(
        company_name=name,
        google_place_id=place_id,
        city=city,
        region=region_key,
        sector=sector,
        website=website,
        phone=phone,
        status="discovered",
        discovery_source=source,
        linkedin_url=linkedin_url,
        careers_url=careers_url,
        job_url=job_url,
    )

    email_added = False
    if website:
        for em in _extract_emails_from_page(website):
            if db.add_email(company_id, em, source, is_primary=False, verified=False):
                email_added = True
        hr = _pick_hr_email(_extract_emails_from_page(website))
        if hr and db.add_email(company_id, hr, source, is_primary=True, verified=False):
            email_added = True
            db.update_company_status(company_id, "email_found")

    if not email_added and website:
        domain = urlparse(website).netloc.replace("www.", "")
        if domain and _host_ok(website):
            for prefix in ("hr", "careers", "recruitment", "jobs"):
                guessed = f"{prefix}@{domain}"
                if db.add_email(company_id, guessed, "domain_pattern", is_primary=True, verified=False):
                    db.update_company_status(company_id, "email_found")
                    email_added = True
                    break

    if is_new:
        stats["new"] += 1
    else:
        stats["updated"] += 1


def discover_linkedin(
    city: str,
    region_key: str,
    config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    config = config or load_config()
    max_q = min(config.get("discovery", {}).get("max_results_per_query", 20), 20)
    stats: dict[str, Any] = {"new": 0, "updated": 0, "skipped": 0, "errors": []}
    seen: set[str] = set()

    queries = _linkedin_queries(config, city)

    for query in queries:
        try:
            for item in _search_duckduckgo(query, max_q):
                url = item.get("website", "")
                name = item.get("name", "")
                key = (name or url).lower()
                if key in seen:
                    continue
                seen.add(key)

                linkedin_url = url if "linkedin.com" in url else None
                website = None if linkedin_url else _normalize_url(url)

                _upsert_candidate(
                    name=name,
                    website=website,
                    city=city,
                    region_key=region_key,
                    source="linkedin",
                    config=config,
                    linkedin_url=linkedin_url,
                    job_url=url if "/jobs/" in url else None,
                    stats=stats,
                )
            time.sleep(2)
        except Exception as exc:
            stats["errors"].append(f"LinkedIn '{query[:40]}': {exc}")

    return stats


def discover_careers_portals(
    city: str,
    region_key: str,
    config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    config = config or load_config()
    max_q = min(config.get("discovery", {}).get("max_results_per_query", 20), 20)
    stats: dict[str, Any] = {"new": 0, "updated": 0, "skipped": 0, "errors": []}
    seen: set[str] = set()

    for query in _careers_queries(config, city):
        try:
            for item in _search_duckduckgo(query, max_q):
                url = item.get("website", "")
                name = item.get("name", "")
                key = (name or url).lower()
                if key in seen:
                    continue
                seen.add(key)

                careers_url = url if any(
                    h in url for h in ("careers-ksa", "bayt.com", "indeed", "glassdoor", "naukrigulf", "gulftalent", "tanqeeb")
                ) else None
                website = _normalize_url(url) if careers_url is None else None

                _upsert_candidate(
                    name=name,
                    website=website,
                    city=city,
                    region_key=region_key,
                    source="careers_portal",
                    config=config,
                    careers_url=careers_url or url,
                    job_url=url,
                    stats=stats,
                )
            time.sleep(2)
        except Exception as exc:
            stats["errors"].append(f"Careers '{query[:40]}': {exc}")

    return stats


def discover_hr_web(
    city: str,
    region_key: str,
    config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    config = config or load_config()
    max_q = min(config.get("discovery", {}).get("max_results_per_query", 15), 15)
    stats: dict[str, Any] = {"new": 0, "updated": 0, "skipped": 0, "errors": [], "emails_found": 0}
    seen: set[str] = set()

    queries = list(HR_EMAIL_QUERIES)
    for q in _city_queries(config).get(city, []):
        queries.append(f'{q} "hr@" OR "careers@" contact')
    queries.extend(_employer_queries(config, city))

    for query in queries:
        try:
            for item in _search_duckduckgo(query, max_q):
                url = item.get("website", "")
                name = item.get("name", "")
                website = _normalize_url(url)
                if not website:
                    continue
                key = website.lower()
                if key in seen:
                    continue
                seen.add(key)

                emails = _extract_emails_from_page(website)
                hr = _pick_hr_email(emails)
                if not hr and not _matches_filters(name, config):
                    stats["skipped"] += 1
                    continue

                _upsert_candidate(
                    name=name or urlparse(website).netloc,
                    website=website,
                    city=city,
                    region_key=region_key,
                    source="deep_search",
                    config=config,
                    stats=stats,
                )
                if hr:
                    stats["emails_found"] = stats.get("emails_found", 0) + 1
            time.sleep(2)
        except Exception as exc:
            stats["errors"].append(f"HR web '{query[:40]}': {exc}")

    return stats


def discover_city_deep(
    city: str,
    region_key: str,
    config: Optional[dict[str, Any]] = None,
    sources: Optional[list[str]] = None,
) -> dict[str, Any]:
    config = config or load_config()
    enabled = sources or config.get("discovery", {}).get("deep_sources", ["linkedin", "careers_portal", "deep_search"])
    merged: dict[str, Any] = {"new": 0, "updated": 0, "skipped": 0, "errors": [], "by_source": {}}

    runners = {
        "linkedin": discover_linkedin,
        "careers_portal": discover_careers_portals,
        "deep_search": discover_hr_web,
    }
    for src in enabled:
        fn = runners.get(src)
        if not fn:
            continue
        result = fn(city, region_key, config)
        merged["by_source"][src] = result
        for k in ("new", "updated", "skipped"):
            merged[k] = merged.get(k, 0) + result.get(k, 0)
        merged["errors"].extend(result.get("errors", []))

    return merged


def discover_target_cities(config: Optional[dict[str, Any]] = None) -> dict[str, dict[str, Any]]:
    config = config or load_config()
    target = config.get("automation", {}).get("target_cities", ["Jeddah", "Abha"])
    region_map = {"Jeddah": "jeddah", "Abha": "abha"}
    results = {}
    for city in target:
        region_key = region_map.get(city, city.lower())
        results[city] = discover_city_deep(city, region_key, config)
        time.sleep(1)
    return results
