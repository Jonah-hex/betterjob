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


def build_subject_for_company(
    company: dict[str, Any],
    config: Optional[dict[str, Any]] = None,
) -> str:
    """Strategy-aware subject when application_strategy is enabled."""
    config = config or load_config()
    if config.get("application_strategy", {}).get("enabled"):
        import application_strategy

        return application_strategy.build_subject(company, config)
    return build_subject(company.get("company_name", ""), config)


def compose_email_ar(
    company_name: str,
    city: str,
    sector: str = "Construction",
    config: Optional[dict[str, Any]] = None,
    title_ar: Optional[str] = None,
    hook_ar: Optional[str] = None,
) -> str:
    config = config or load_config()
    p = config["profile"]
    template = _load_template("email_ar.txt")

    return template.format(
        company_name=company_name,
        city=city,
        sector=sector,
        full_name=p["full_name_ar"],
        title=title_ar or p["title_ar"],
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
    title_en: Optional[str] = None,
    hook_en: Optional[str] = None,
) -> str:
    config = config or load_config()
    p = config["profile"]
    template = _load_template("email_en.txt")

    return template.format(
        company_name=company_name,
        city=city,
        sector=sector,
        full_name=p["full_name"],
        title=title_en or p["title"],
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
    use_strategy: bool = True,
    project_line_ar: Optional[str] = None,
    project_line_en: Optional[str] = None,
) -> dict[str, str]:
    name = company.get("company_name", "")
    city = company.get("city", "")
    sector = company.get("sector", "Construction")
    config = config or load_config()

    title_ar = None
    title_en = None
    hook_ar = ""
    hook_en = ""

    if use_strategy and config.get("application_strategy", {}).get("enabled"):
        import application_strategy

        meta = application_strategy.classify_tier(company, config)
        hook = application_strategy.get_hook(meta["hook_key"], config)
        title_ar = meta["job_title_ar"]
        title_en = meta["job_title_en"]
        hook_ar = hook["ar"]
        hook_en = hook["en"]
        subject = application_strategy.build_subject(company, config)
    else:
        subject = build_subject(name, config)

    body_ar = compose_email_ar(
        name, city, sector, config, title_ar=title_ar, hook_ar=hook_ar or None
    )
    body_en = compose_email_en(
        name, city, sector, config, title_en=title_en, hook_en=hook_en or None
    )

    if hook_ar:
        body_ar = body_ar.replace(
            "أرفق سيرتي الذاتية",
            f"{hook_ar}\n\nأرفق سيرتي الذاتية",
            1,
        )
    if hook_en:
        body_en = body_en.replace(
            "Please find my CV attached in PDF format.",
            f"{hook_en}\n\nPlease find my CV attached in PDF format.",
            1,
        )

    if project_line_ar:
        body_ar = body_ar.replace(
            "تحية طيبة وبعد،",
            f"تحية طيبة وبعد،\n\n{project_line_ar}",
            1,
        )
    if project_line_en:
        body_en = body_en.replace(
            "I am writing to express my interest",
            f"{project_line_en}\n\nI am writing to express my interest",
            1,
        )

    return {
        "subject": subject,
        "body_ar": body_ar,
        "body_en": body_en,
        "title_en": title_en or config["profile"]["title"],
        "title_ar": title_ar or config["profile"]["title_ar"],
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
