"""Compose HR cover letter emails (Arabic + English) — NOT full CV."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

TEMPLATES_DIR = Path(__file__).parent / "templates"


def load_config(path: str = "config.yaml") -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_template(name: str) -> str:
    path = TEMPLATES_DIR / name
    return path.read_text(encoding="utf-8")


def build_subject(company_name: str, config: Optional[dict[str, Any]] = None) -> str:
    config = config or load_config()
    profile = config["profile"]
    subject = (
        f"Application — General Land Surveyor | Total Station | {profile['full_name']}"
    )
    return subject[:60]


def compose_email_ar(
    company_name: str,
    city: str,
    sector: str = "Construction",
    config: Optional[dict[str, Any]] = None,
) -> str:
    config = config or load_config()
    p = config["profile"]
    template = _load_template("email_ar.txt")

    return template.format(
        company_name=company_name,
        city=city,
        sector=sector,
        full_name=p["full_name_ar"],
        title=p["title_ar"],
        years_experience=p["years_experience"],
        total_station_brands=p["total_station_brands"],
        software=p["software"],
        phone=p["phone"],
        sender_email=p["sender_email"],
        sce_membership=p.get("sce_membership", ""),
    ).strip()


def compose_email_en(
    company_name: str,
    city: str,
    sector: str = "Construction",
    config: Optional[dict[str, Any]] = None,
) -> str:
    config = config or load_config()
    p = config["profile"]
    template = _load_template("email_en.txt")

    return template.format(
        company_name=company_name,
        city=city,
        sector=sector,
        full_name=p["full_name"],
        title=p["title"],
        years_experience=p["years_experience"],
        total_station_brands=p["total_station_brands"],
        software=p["software"],
        phone=p["phone"],
        sender_email=p["sender_email"],
        sce_membership=p.get("sce_membership", ""),
    ).strip()


def compose_for_company(
    company: dict[str, Any],
    config: Optional[dict[str, Any]] = None,
) -> dict[str, str]:
    name = company.get("company_name", "")
    city = company.get("city", "")
    sector = company.get("sector", "Construction")

    return {
        "subject": build_subject(name, config),
        "body_ar": compose_email_ar(name, city, sector, config),
        "body_en": compose_email_en(name, city, sector, config),
    }


def get_cv_prompt(config: Optional[dict[str, Any]] = None) -> str:
    config = config or load_config()
    prompt_path = TEMPLATES_DIR / "cv_prompt.md"
    content = prompt_path.read_text(encoding="utf-8")
    keywords = ", ".join(config.get("cv_ats_keywords", []))
    p = config["profile"]
    return content.replace("{KEYWORDS}", keywords).replace(
        "{FULL_NAME}", p["full_name"]
    )
