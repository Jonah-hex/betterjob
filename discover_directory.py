"""Discover companies from web directories and search engines (no API key)."""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import yaml
from bs4 import BeautifulSoup

import database as db
import outreach_quality

USER_AGENT = "BetterJob-Outreach/1.0 (job-search; directory-discovery)"
SKIP_HOSTS = {
    "facebook.com", "twitter.com", "x.com", "instagram.com", "linkedin.com",
    "youtube.com", "wikipedia.org", "google.com", "play.google.com",
    "apps.apple.com", "yellowpages.com", "indeed.com", "bayt.com",
    "gulftalent.com", "naukrigulf.com", "ejobsboard.com", "glassdoor.com",
    "tanqeeb.com", "careers-ksa.com", "homerun.com", "gethomerun.com",
    "jooble.com", "neuvoo.com", "jobrapido.com",
}

CITY_QUERIES = {
    "Jeddah": [
        "مقاولات جدة السعودية",
        "شركات هندسة مدنية جدة",
        "شركات مساحة جدة",
        "استشارات هندسية جدة",
        "construction company Jeddah Saudi Arabia",
        "engineering consultant Jeddah",
        "land surveying company Jeddah",
    ],
    "Abha": [
        "مقاولات أبها السعودية",
        "شركات هندسة أبها",
        "استشارات هندسية عسير",
        "construction company Abha Saudi Arabia",
        "engineering consultant Abha",
    ],
}

YELLOW_PAGES = {
    "Jeddah": "https://www.yellowpages.com.sa/search/jeddah/construction-companies",
    "Abha": "https://www.yellowpages.com.sa/search/abha/construction-companies",
}


def load_config(path: str = "config.yaml") -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _place_id(source: str, name: str, url: str) -> str:
    raw = f"{source}-{name}-{url}".lower().strip()
    return hashlib.md5(raw.encode()).hexdigest()


def _clean_name(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*[-|–]\s*(جدة|أبها|Jeddah|Abha|Saudi.*)$", "", text, flags=re.I)
    return text[:120]


_JUNK_NAME_RE = re.compile(
    r"|".join(
        [
            r"top\s*\+?\s*\d+",
            r"best\s+.+\s+companies\s+in",
            r"^\d+\s+best\s+",
            r"companies\s+in\s+\w+",
            r"construction\s+of\s+buildings\s+companies",
            r"business\s+director",
            r"hiring\s+",
            r"jobs?\s+in\s+",
            r"job\s+at\s+",
            r"\|\s*jobs",
            r"land\s+surveyor\s+jobs?",
            r"surveyor\s+jobs?\s+in",
            r"^about\s+us\s+-",
        ]
    ),
    re.I,
)


def _is_listing_junk(name: str) -> bool:
    text = name.strip()
    if len(text) > 90:
        return True
    return bool(_JUNK_NAME_RE.search(text))


def _host_ok(url: str) -> bool:
    host = urlparse(url).netloc.lower().replace("www.", "")
    return bool(host) and not any(skip in host for skip in SKIP_HOSTS)


def _normalize_url(url: str) -> Optional[str]:
    if not url or not url.startswith("http"):
        return None
    parsed = urlparse(url)
    if not _host_ok(url):
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _infer_sector(name: str, url: str) -> str:
    text = f"{name} {url}".lower()
    if "survey" in text or "مساح" in name:
        return "Surveying"
    if "engineer" in text or "هندس" in name or "consult" in text:
        return "Engineering"
    return "Construction"


def _matches_filters(name: str, config: dict[str, Any]) -> bool:
    if _is_listing_junk(name):
        return False
    text = name.lower()
    exclude = [k.lower() for k in config.get("filters", {}).get("exclude_keywords", [])]
    if any(kw in text for kw in exclude):
        return False
    keywords = [k.lower() for k in config.get("filters", {}).get("include_keywords", [])]
    return any(kw in text for kw in keywords) if keywords else len(name) >= 4


def _search_duckduckgo(query: str, max_results: int = 15) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    try:
        with httpx.Client(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = client.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query, "kl": "ar-sa"},
            )
            response.raise_for_status()
    except httpx.HTTPError:
        return results

    soup = BeautifulSoup(response.text, "html.parser")
    for link in soup.select("a.result__a"):
        title = _clean_name(link.get_text(strip=True))
        href = link.get("href", "")
        if "uddg=" in href:
            parsed = parse_qs(urlparse(href).query)
            href = unquote(parsed.get("uddg", [""])[0])
        website = _normalize_url(href)
        if title and website:
            results.append({"name": title, "website": website})
        if len(results) >= max_results:
            break
    return results


def _scrape_yellowpages(city: str, max_results: int = 20) -> list[dict[str, str]]:
    url = YELLOW_PAGES.get(city)
    if not url:
        return []

    results: list[dict[str, str]] = []
    try:
        with httpx.Client(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = client.get(url)
            if response.status_code >= 400:
                return results
            soup = BeautifulSoup(response.text, "html.parser")
    except httpx.HTTPError:
        return results

    for card in soup.select(".business-name, .company-name, h2 a, h3 a, .listing-title"):
        name = _clean_name(card.get_text(strip=True))
        href = card.get("href", "") if card.name == "a" else ""
        parent_link = card.find_parent("a")
        if parent_link and parent_link.get("href"):
            href = parent_link.get("href", "")
        website = _normalize_url(href) if href.startswith("http") else None
        if name and len(name) >= 4:
            results.append({"name": name, "website": website or ""})
        if len(results) >= max_results:
            break
    return results


def discover_city_directory(
    city: str,
    region_key: str,
    config: Optional[dict[str, Any]] = None,
) -> dict[str, int]:
    config = config or load_config()
    max_per_query = min(config.get("discovery", {}).get("max_results_per_query", 20), 25)
    stats = {"new": 0, "updated": 0, "skipped": 0, "errors": []}
    seen: set[str] = set()

    candidates: list[dict[str, str]] = []
    for query in CITY_QUERIES.get(city, []):
        try:
            candidates.extend(_search_duckduckgo(query, max_per_query))
            time.sleep(2)
        except Exception as exc:
            stats["errors"].append(f"بحث '{query}': {exc}")

    try:
        candidates.extend(_scrape_yellowpages(city, max_per_query))
    except Exception as exc:
        stats["errors"].append(f"YellowPages {city}: {exc}")

    for item in candidates:
        name = item.get("name", "").strip()
        website = item.get("website") or None
        if not name:
            stats["skipped"] += 1
            continue

        key = name.lower()
        if key in seen:
            stats["skipped"] += 1
            continue
        seen.add(key)

        if not _matches_filters(name, config):
            stats["skipped"] += 1
            continue

        if outreach_quality.is_excluded_company(name, website, config=config):
            stats["skipped"] += 1
            continue

        if outreach_quality.is_listing_company(name, website, config=config):
            stats["skipped"] += 1
            continue

        place_id = _place_id("directory", name, website or city)
        sector = _infer_sector(name, website or "")

        company_id, is_new = db.upsert_company(
            company_name=name,
            google_place_id=place_id,
            city=city,
            region=region_key,
            sector=sector,
            website=website,
            status="discovered",
            discovery_source="directory",
        )

        if website:
            domain = urlparse(website).netloc.replace("www.", "")
            # لا تخمين إيميل من روابط الدليل — الاستخراج من الموقع لاحقاً
            if domain and _host_ok(website):
                pass

        if is_new:
            stats["new"] += 1
        else:
            stats["updated"] += 1

    return stats


def discover_target_cities(config: Optional[dict[str, Any]] = None) -> dict[str, dict[str, int]]:
    config = config or load_config()
    target = config.get("automation", {}).get("target_cities", ["Jeddah", "Abha"])
    region_map = {"Jeddah": "jeddah", "Abha": "abha"}
    results = {}
    for city in target:
        region_key = region_map.get(city, city.lower())
        results[city] = discover_city_directory(city, region_key, config)
        time.sleep(1)
    return results
