"""Import companies from CSV — no API key needed."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from typing import Any, Optional

import database as db

BASE_DIR = Path(__file__).parent


def _place_id(name: str, city: str) -> str:
    return hashlib.md5(f"csv-{name}-{city}".encode()).hexdigest()


def import_csv(
    csv_path: str | Path,
    default_city: str = "Jeddah",
    default_region: str = "jeddah",
) -> dict[str, int]:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"الملف غير موجود: {path}")

    stats = {"imported": 0, "skipped": 0, "with_email": 0}

    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("company_name") or "").strip()
            if not name:
                stats["skipped"] += 1
                continue

            city = (row.get("city") or default_city).strip()
            region = "jeddah" if city.lower() == "jeddah" else "abha" if city.lower() == "abha" else default_region
            sector = (row.get("sector") or "Construction").strip()
            website = (row.get("website") or "").strip() or None
            phone = (row.get("phone") or "").strip() or None
            email = (row.get("email") or "").strip().lower()

            company_id, is_new = db.upsert_company(
                company_name=name,
                google_place_id=_place_id(name, city),
                city=city,
                region=region,
                sector=sector,
                website=website,
                phone=phone,
                status="discovered",
            )

            if email and "@" in email:
                db.add_email(company_id, email, "manual", is_primary=True, verified=True)
                db.update_company_status(company_id, "email_found")
                stats["with_email"] += 1

            if is_new:
                stats["imported"] += 1
            else:
                stats["skipped"] += 1

    return stats
