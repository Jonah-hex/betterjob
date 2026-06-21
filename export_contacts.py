"""Export company contacts — emails, websites, fit scores to Excel."""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any, Optional

import pandas as pd
import yaml

import database as db
import job_fit
import outreach_quality

STATUS_AR = {
    "discovered": "مكتشفة",
    "email_found": "إيميل موجود",
    "no_email": "بدون إيميل",
    "approved": "معتمدة",
    "sent": "مُرسلة",
    "replied": "ردّت",
}


def load_config(path: str = "config.yaml") -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_contacts_dataframe(
    config: Optional[dict[str, Any]] = None,
    cities: Optional[list[str]] = None,
    with_email_only: bool = False,
) -> pd.DataFrame:
    config = config or load_config()
    cities = cities or config.get("automation", {}).get("target_cities")
    companies = db.get_companies()
    if cities:
        companies = [c for c in companies if c.get("city") in cities]

    ranked = job_fit.rank_companies(companies, config)
    rows: list[dict[str, Any]] = []

    for c in ranked:
        email = c.get("primary_email") or ""
        source = c.get("email_source") or ""
        if with_email_only and not email:
            continue
        rows.append({
            "الشركة": c.get("company_name", ""),
            "المدينة": c.get("city", ""),
            "القطاع": c.get("sector", ""),
            "الموقع الإلكتروني": c.get("website", "") or "",
            "الإيميل": email,
            "مصدر الإيميل": source,
            "جودة الإيميل": outreach_quality.email_tier_label(email, source) if email else "",
            "ملاءمة %": c.get("job_fit_score", 0),
            "الجوال": c.get("phone", "") or "",
            "LinkedIn": c.get("linkedin_url", "") or "",
            "مصدر الاكتشاف": c.get("discovery_source", ""),
            "الحالة": STATUS_AR.get(c.get("status", ""), c.get("status", "")),
        })

    return pd.DataFrame(rows)


def dataframe_to_excel_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="جهات الاتصال")
        ws = writer.sheets["جهات الاتصال"]
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 45)
    buffer.seek(0)
    return buffer.getvalue()


def export_filename(prefix: str = "betterjob_contacts") -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    return f"{prefix}_{ts}.xlsx"
