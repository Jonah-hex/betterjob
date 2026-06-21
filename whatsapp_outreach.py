"""WhatsApp outreach helpers — Saudi phone normalization and wa.me links."""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import quote

import yaml

import database as db

BASE_MESSAGE_AR = (
    "السلام عليكم،\n"
    "أنا {name} — {title} بخبرة {years} سنة في المساحة والـ Total Station.\n"
    "أرسلت سيرتي الذاتية على بريد الشركة، وأرفق نسخة هنا للاطلاع.\n"
    "شاكراً لوقتكم."
)

BASE_MESSAGE_EN = (
    "Hello,\n"
    "I am {name} — {title} with {years} years in land surveying & Total Station.\n"
    "I also sent my CV to your company email. Please find a copy here for your review.\n"
    "Thank you."
)


def load_config(path: str = "config.yaml") -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def normalize_saudi_phone(phone: str) -> Optional[str]:
    """Return E.164 digits without + for wa.me (e.g. 9665XXXXXXXX)."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("00966"):
        digits = digits[2:]
    if digits.startswith("966") and len(digits) >= 12:
        return digits[:12]
    if digits.startswith("05") and len(digits) == 10:
        return "966" + digits[1:]
    if digits.startswith("5") and len(digits) == 9:
        return "966" + digits
    if len(digits) >= 10:
        return digits
    return None


def build_whatsapp_url(phone: str, message: str) -> Optional[str]:
    normalized = normalize_saudi_phone(phone)
    if not normalized:
        return None
    return f"https://wa.me/{normalized}?text={quote(message)}"


def compose_message(company: dict[str, Any], config: Optional[dict[str, Any]] = None) -> str:
    config = config or load_config()
    p = config["profile"]
    ar = BASE_MESSAGE_AR.format(
        name=p.get("full_name_ar", p["full_name"]),
        title=p.get("title_ar", p["title"]),
        years=p.get("years_experience", 12),
    )
    en = BASE_MESSAGE_EN.format(
        name=p["full_name"],
        title=p["title"],
        years=p.get("years_experience", 12),
    )
    company_name = company.get("company_name", "")
    if company_name:
        ar = f"تحية طيبة لـ {company_name}\n\n" + ar
        en = f"Dear {company_name},\n\n" + en
    return f"{ar}\n\n---\n\n{en}"


def get_companies_with_phones(
    cities: Optional[list[str]] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    companies = db.get_companies()
    rows = []
    for c in companies:
        if cities and c.get("city") not in cities:
            continue
        phone = c.get("phone")
        if not phone:
            continue
        wa = build_whatsapp_url(phone, compose_message(c))
        if not wa:
            continue
        row = dict(c)
        row["whatsapp_url"] = wa
        row["phone_normalized"] = normalize_saudi_phone(phone)
        rows.append(row)
    return rows[:limit]


def log_outreach(
    company_id: int,
    phone: str,
    message: str,
    status: str = "opened",
) -> int:
    return db.log_whatsapp(company_id, phone, message, status)


def batch_links(
    companies: list[dict[str, Any]],
    config: Optional[dict[str, Any]] = None,
) -> list[dict[str, str]]:
    links = []
    for c in companies:
        msg = compose_message(c, config)
        url = build_whatsapp_url(c.get("phone", ""), msg)
        if url:
            links.append({
                "company": c.get("company_name", ""),
                "phone": c.get("phone", ""),
                "url": url,
                "company_id": c.get("id"),
            })
    return links
