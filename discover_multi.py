"""Multi-source company discovery — Google, OSM, CSV, directories, domains."""

from __future__ import annotations

import os
from typing import Any, Optional

import yaml
from dotenv import load_dotenv

import database as db
import discover
import discover_domains
import discover_directory
import discover_overpass
import import_csv
from pathlib import Path

load_dotenv()
BASE_DIR = Path(__file__).parent

SOURCE_LABELS = {
    "csv": "ملف CSV",
    "google": "Google Places",
    "overpass": "OpenStreetMap",
    "directory": "دليل ويب / بحث",
    "domains": "استنتاج من الدومين",
}


def load_config(path: str = "config.yaml") -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _enabled_sources(config: dict[str, Any]) -> list[str]:
    discovery = config.get("discovery", {})
    sources = discovery.get("sources")
    if sources:
        return list(sources)
    provider = config.get("discovery_provider", "multi")
    if provider == "csv":
        return ["csv"]
    if provider == "google":
        return ["google"]
    if provider == "overpass":
        return ["overpass"]
    return ["csv", "google", "overpass", "directory", "domains"]


def discover_all_sources(config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Run all enabled discovery sources and return aggregated stats."""
    config = config or load_config()
    db.init_db()
    sources = _enabled_sources(config)
    summary: dict[str, Any] = {"sources_run": [], "by_source": {}, "total_new": 0}

    if "csv" in sources:
        csv_path = BASE_DIR / "data" / "companies.csv"
        if csv_path.exists():
            stats = import_csv.import_csv(csv_path)
            summary["by_source"]["csv"] = stats
            summary["sources_run"].append("csv")
            summary["total_new"] += stats.get("imported", 0)

    if "google" in sources:
        api_key = os.getenv("GOOGLE_PLACES_API_KEY", "")
        if api_key and not api_key.startswith("your_"):
            try:
                results = discover.discover_target_cities(config)
                new_count = sum(r.get("new", 0) for r in results.values())
                summary["by_source"]["google"] = results
                summary["sources_run"].append("google")
                summary["total_new"] += new_count
            except Exception as exc:
                summary["by_source"]["google"] = {"errors": [str(exc)]}
        else:
            summary["by_source"]["google"] = {"skipped": "GOOGLE_PLACES_API_KEY غير موجود"}

    if "overpass" in sources:
        try:
            results = discover_overpass.discover_target_cities(config)
            new_count = sum(r.get("new", 0) for r in results.values())
            summary["by_source"]["overpass"] = results
            summary["sources_run"].append("overpass")
            summary["total_new"] += new_count
        except Exception as exc:
            summary["by_source"]["overpass"] = {"errors": [str(exc)]}

    if "directory" in sources:
        try:
            results = discover_directory.discover_target_cities(config)
            new_count = sum(r.get("new", 0) for r in results.values())
            summary["by_source"]["directory"] = results
            summary["sources_run"].append("directory")
            summary["total_new"] += new_count
        except Exception as exc:
            summary["by_source"]["directory"] = {"errors": [str(exc)]}

    if "domains" in sources:
        try:
            stats = discover_domains.enrich_all_pending(config)
            summary["by_source"]["domains"] = stats
            summary["sources_run"].append("domains")
            summary["total_new"] += stats.get("email_found", 0)
        except Exception as exc:
            summary["by_source"]["domains"] = {"errors": [str(exc)]}

    return summary


def discover_target_cities(config: Optional[dict[str, Any]] = None) -> dict[str, dict[str, int]]:
    """Compatibility wrapper for auto_run — returns city-level stats."""
    summary = discover_all_sources(config)
    merged: dict[str, dict[str, int]] = {}

    for source, data in summary.get("by_source", {}).items():
        if source in ("csv", "domains"):
            merged[source] = data if isinstance(data, dict) else {}
            continue
        if isinstance(data, dict):
            for city, stats in data.items():
                if isinstance(stats, dict) and "new" in stats:
                    if city not in merged:
                        merged[city] = {"new": 0, "updated": 0, "skipped": 0, "errors": []}
                    for key in ("new", "updated", "skipped"):
                        merged[city][key] = merged[city].get(key, 0) + stats.get(key, 0)
                    merged[city]["errors"].extend(stats.get("errors", []))

    if not merged:
        merged["multi"] = {"new": summary.get("total_new", 0), "updated": 0, "skipped": 0}
    return merged
