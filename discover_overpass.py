"""Discover companies via OpenStreetMap Overpass API — free, no API key."""

from __future__ import annotations

import hashlib
import time
from typing import Any, Optional

import httpx
import yaml

import database as db

OVERPASS_URL = "https://overpass.kumi.systems/api/interpreter"

CITY_BBOX = {
    "Jeddah": (21.25, 39.05, 21.75, 39.35),
    "Abha": (18.15, 42.45, 18.35, 42.65),
}
USER_AGENT = "BetterJob-Outreach/1.0 (job-application; overpass)"

# OSM tags relevant to construction / engineering / surveying
OSM_QUERIES = """
  node["office"="engineer"](area.searchArea);
  way["office"="engineer"](area.searchArea);
  node["office"="architect"](area.searchArea);
  way["office"="architect"](area.searchArea);
  node["office"="construction_company"](area.searchArea);
  way["office"="construction_company"](area.searchArea);
  node["craft"="builder"](area.searchArea);
  way["craft"="builder"](area.searchArea);
  node["landuse"="construction"](area.searchArea);
  node["man_made"="works"](area.searchArea);
  node["company"](area.searchArea);
  way["company"](area.searchArea);
"""


def load_config(path: str = "config.yaml") -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _place_id_from_name(name: str, lat: float, lon: float) -> str:
    raw = f"osm-{name}-{lat:.5f}-{lon:.5f}"
    return hashlib.md5(raw.encode()).hexdigest()


def _get_tag(element: dict, key: str) -> Optional[str]:
    return element.get("tags", {}).get(key)


def _element_name(element: dict) -> str:
    tags = element.get("tags", {})
    for key in ("name", "name:ar", "name:en", "brand", "operator"):
        if tags.get(key):
            return tags[key]
    return ""


def _element_coords(element: dict) -> tuple[float, float]:
    if element.get("type") == "node":
        return float(element.get("lat", 0)), float(element.get("lon", 0))
    center = element.get("center", {})
    return float(center.get("lat", 0)), float(center.get("lon", 0))


def _matches_keywords(name: str, tags: dict, config: dict) -> bool:
    keywords = [k.lower() for k in config.get("filters", {}).get("include_keywords", [])]
    text = f"{name} {' '.join(str(v) for v in tags.values())}".lower()
    return any(kw in text for kw in keywords)


def _infer_sector(tags: dict, name: str) -> str:
    text = f"{name} {' '.join(str(v) for v in tags.values())}".lower()
    if "survey" in text or "مساح" in name:
        return "Surveying"
    if "engineer" in text or "architect" in text or "هندس" in name:
        return "Engineering"
    return "Construction"


def _build_query_bbox(city: str) -> str:
    south, west, north, east = CITY_BBOX.get(city, (0, 0, 0, 0))
    return f"""
    [out:json][timeout:90];
    (
      node["office"~"engineer|architect|construction_company"]({south},{west},{north},{east});
      way["office"~"engineer|architect|construction_company"]({south},{west},{north},{east});
      node["craft"="builder"]({south},{west},{north},{east});
      way["craft"="builder"]({south},{west},{north},{east});
      node["company"]({south},{west},{north},{east});
      way["company"]({south},{west},{north},{east});
    );
    out body center tags;
    """


def _build_query(city: str) -> str:
    if city in CITY_BBOX:
        return _build_query_bbox(city)
    return f"""
    [out:json][timeout:90];
    area["name:en"="{city}"]->.searchArea;
    (
      {OSM_QUERIES}
    );
    out body center tags;
    """


def _fetch_overpass(query: str) -> list[dict]:
    with httpx.Client(timeout=120, headers={"User-Agent": USER_AGENT}) as client:
        response = client.post(OVERPASS_URL, data={"data": query})
        response.raise_for_status()
        return response.json().get("elements", [])


def discover_city_overpass(
    city: str,
    region_key: str,
    config: Optional[dict[str, Any]] = None,
) -> dict[str, int]:
    config = config or load_config()
    stats = {"new": 0, "updated": 0, "skipped": 0, "errors": []}

    try:
        elements = _fetch_overpass(_build_query(city))
    except httpx.HTTPError as exc:
        stats["errors"].append(str(exc))
        return stats

    seen_names: set[str] = set()

    for element in elements:
        name = _element_name(element)
        if not name or len(name) < 3:
            stats["skipped"] += 1
            continue

        tags = element.get("tags", {})
        if not _matches_keywords(name, tags, config):
            stats["skipped"] += 1
            continue

        name_key = name.lower().strip()
        if name_key in seen_names:
            stats["skipped"] += 1
            continue
        seen_names.add(name_key)

        lat, lon = _element_coords(element)
        website = _get_tag(element, "website") or _get_tag(element, "contact:website")
        phone = _get_tag(element, "phone") or _get_tag(element, "contact:phone")
        email = _get_tag(element, "email") or _get_tag(element, "contact:email")
        sector = _infer_sector(tags, name)
        place_id = _place_id_from_name(name, lat, lon)

        company_id, is_new = db.upsert_company(
            company_name=name,
            google_place_id=place_id,
            city=city,
            region=region_key,
            sector=sector,
            website=website,
            phone=phone,
            place_types=list(tags.keys())[:10],
            status="discovered",
        )

        if email and "@" in email:
            db.add_email(company_id, email, "found_on_page", is_primary=True, verified=True)
            db.update_company_status(company_id, "email_found")

        if is_new:
            stats["new"] += 1
        else:
            stats["updated"] += 1

        time.sleep(0.05)

    return stats


def discover_target_cities(config: Optional[dict[str, Any]] = None) -> dict[str, dict[str, int]]:
    config = config or load_config()
    target = config.get("automation", {}).get("target_cities", ["Jeddah", "Abha"])
    region_map = {"Jeddah": "jeddah", "Abha": "abha"}

    results = {}
    for city in target:
        region_key = region_map.get(city, city.lower())
        results[city] = discover_city_overpass(city, region_key, config)
        time.sleep(2)
    return results
