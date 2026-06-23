"""Discover construction/engineering/survey companies via Google Places API (New)."""

from __future__ import annotations

import os
import re
from typing import Any, Optional

import httpx
import yaml
from dotenv import load_dotenv

import database as db

load_dotenv()

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.websiteUri,places.nationalPhoneNumber,places.types"
)


def load_config(path: str = "config.yaml") -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _normalize_place_id(place_id: str) -> str:
    return place_id.replace("places/", "") if place_id.startswith("places/") else place_id


def _matches_filters(name: str, types: list[str], config: dict[str, Any]) -> bool:
    filters = config.get("filters", {})
    exclude = set(filters.get("exclude_types", []))
    include_kw = [k.lower() for k in filters.get("include_keywords", [])]

    type_set = {t.lower() for t in types}
    if type_set & exclude:
        return False

    text = f"{name} {' '.join(types)}".lower()
    return any(kw in text for kw in include_kw)


def _infer_city(address: str, cities: list[str]) -> Optional[str]:
    address_lower = address.lower()
    for city in cities:
        if city.lower() in address_lower:
            return city
    return None


def _infer_sector(types: list[str], name: str) -> str:
    text = f"{' '.join(types)} {name}".lower()
    if "survey" in text or "مساح" in name:
        return "Surveying"
    if "engineering" in text or "هندس" in name:
        return "Engineering"
    return "Construction"


def search_places(
    text_query: str,
    api_key: str,
    language: str = "ar",
    max_results: int = 20,
) -> list[dict[str, Any]]:
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    body = {
        "textQuery": text_query,
        "languageCode": language,
        "maxResultCount": max_results,
        "regionCode": "SA",
    }

    with httpx.Client(timeout=30) as client:
        response = client.post(PLACES_URL, headers=headers, json=body)
        response.raise_for_status()
        data = response.json()

    return data.get("places", [])


def discover_region(
    region_key: str,
    config: Optional[dict[str, Any]] = None,
    api_key: Optional[str] = None,
) -> dict[str, int]:
    config = config or load_config()
    api_key = api_key or os.getenv("GOOGLE_PLACES_API_KEY", "")
    if not api_key:
        raise ValueError("GOOGLE_PLACES_API_KEY غير موجود في .env")

    region = config["regions"][region_key]
    cities = region["cities"]
    queries = region.get("queries_ar", []) + region.get("queries_en", [])
    max_results = min(config.get("discovery", {}).get("max_results_per_query", 20), 20)
    language = config.get("discovery", {}).get("language", "ar")

    stats = {"new": 0, "updated": 0, "skipped": 0, "total_queries": len(queries), "errors": []}

    for query in queries:
        try:
            places = search_places(query, api_key, language, max_results)
        except httpx.HTTPStatusError as exc:
            err_body = ""
            try:
                err_body = exc.response.json().get("error", {}).get("message", "")
            except Exception:
                err_body = str(exc)
            err_msg = f"'{query}': {err_body}"
            stats["errors"].append(err_msg)
            try:
                print(f"خطأ في البحث {err_msg}")
            except (OSError, UnicodeEncodeError):
                pass
            continue
        except httpx.HTTPError as exc:
            stats["errors"].append(f"'{query}': {exc}")
            try:
                print(f"خطأ في البحث '{query}': {exc}")
            except (OSError, UnicodeEncodeError):
                pass
            continue

        for place in places:
            name = place.get("displayName", {}).get("text", "")
            types = place.get("types", [])
            if not _matches_filters(name, types, config):
                stats["skipped"] += 1
                continue

            address = place.get("formattedAddress", "")
            city = _infer_city(address, cities) or cities[0]
            place_id = _normalize_place_id(place.get("id", ""))
            if not place_id:
                stats["skipped"] += 1
                continue

            website = place.get("websiteUri")
            phone = place.get("nationalPhoneNumber")
            sector = _infer_sector(types, name)

            _, is_new = db.upsert_company(
                company_name=name,
                google_place_id=place_id,
                city=city,
                region=region_key,
                sector=sector,
                website=website,
                phone=phone,
                place_types=types,
                status="discovered",
                discovery_source="google",
            )
            if is_new:
                stats["new"] += 1
            else:
                stats["updated"] += 1

    return stats


def discover_all(config: Optional[dict[str, Any]] = None) -> dict[str, dict[str, int]]:
    config = config or load_config()
    results = {}
    for region_key in config.get("regions", {}):
        results[region_key] = discover_region(region_key, config)
    return results


def discover_target_cities(config: Optional[dict[str, Any]] = None) -> dict[str, dict[str, int]]:
    """Discover companies only in automation target cities (Jeddah, Abha)."""
    config = config or load_config()
    auto = config.get("automation", {})
    target = auto.get("target_cities", ["Jeddah", "Abha"])

    region_map = {"Jeddah": "jeddah", "Abha": "abha"}
    results = {}
    for city in target:
        region_key = region_map.get(city)
        if region_key and region_key in config.get("regions", {}):
            results[city] = discover_region(region_key, config)
    return results


if __name__ == "__main__":
    db.init_db()
    results = discover_all()
    for region, stats in results.items():
        print(f"{region}: {stats}")
