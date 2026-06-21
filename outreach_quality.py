"""Outreach quality — prioritize by fit, filter weak emails, WhatsApp follow-up targets."""

from __future__ import annotations

from typing import Any, Optional

import yaml

import database as db
import job_fit

HR_PREFIXES = ("hr", "careers", "recruitment", "jobs", "hiring", "talent", "recruit")
WEAK_PREFIXES = ("info", "contact", "admin", "sales", "support", "office")
VERIFIED_SOURCES = frozenset({
    "found_on_page",
    "manual",
    "csv",
    "google_places",
})
INFERRED_SOURCES = frozenset({
    "directory",
    "domain_pattern",
    "deep_search",
    "linkedin",
    "careers_portal",
})
SKIP_EMAIL_DOMAIN_FRAGMENTS = (
    "yellowpages",
    "arablocal",
    "haraj.com",
    "price-ksa",
    "niche5ar",
    "dalilmadina",
    "babelsoftco",
    "thecircle.sa",
    "dnb.com",
    "wikipedia",
    "facebook",
    "linkedin",
    "google",
    "indeed",
    "bayt",
)


def load_config(path: str = "config.yaml") -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def quality_settings(config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    config = config or load_config()
    defaults = {
        "min_fit_score": 40,
        "prioritize_by_fit": True,
        "skip_weak_domain_emails": True,
        "whatsapp_followup_top": 30,
        "whatsapp_min_fit": 50,
        "whatsapp_skip_recent_days": 7,
    }
    merged = dict(defaults)
    merged.update(config.get("outreach_quality", {}))
    return merged


def email_local_part(email: str) -> str:
    return (email or "").split("@")[0].lower().strip()


def _email_domain(email: str) -> str:
    return email.split("@")[1].lower() if "@" in email else ""


def is_skip_email_domain(email: str) -> bool:
    domain = _email_domain(email)
    return any(frag in domain for frag in SKIP_EMAIL_DOMAIN_FRAGMENTS)


def classify_email(email: str, source: str, verified: bool = False) -> str:
    """
    Tier: hr | verified | ok | weak | blocked
    """
    if not email or "@" not in email:
        return "blocked"
    if source == "guessed" or is_skip_email_domain(email):
        return "blocked"

    local = email_local_part(email)

    if source in VERIFIED_SOURCES or verified:
        if any(local == p or local.startswith(f"{p}.") for p in HR_PREFIXES):
            return "hr"
        return "verified"

    # إيميلات مُستنتجة من الدليل/الدومين — لا تُرسل تلقائياً حتى لو careers@
    if source in INFERRED_SOURCES:
        return "weak"

    if any(local == p or local.startswith(f"{p}.") for p in HR_PREFIXES):
        return "hr"

    if source in ("domain_pattern", "directory", "deep_search") and local in WEAK_PREFIXES:
        return "weak"

    return "ok"


def is_auto_send_allowed(
    email: str,
    source: str,
    config: Optional[dict[str, Any]] = None,
    verified: bool = False,
) -> bool:
    cfg = quality_settings(config)
    tier = classify_email(email, source, verified=verified)
    if tier == "blocked":
        return False
    if tier == "weak" and cfg.get("skip_weak_domain_emails", True):
        return False
    return True


def email_tier_label(email: str, source: str, verified: bool = False) -> str:
    labels = {
        "hr": "🎯 HR",
        "verified": "✅ موثّق",
        "ok": "📧 عادي",
        "weak": "⚠️ ضعيف",
        "blocked": "🚫 محظور",
    }
    return labels.get(classify_email(email, source, verified=verified), "—")


def prioritize_sendable(
    companies: list[dict[str, Any]],
    config: Optional[dict[str, Any]] = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (allowed, skipped) sorted by job fit descending."""
    cfg = quality_settings(config)
    min_fit = int(cfg.get("min_fit_score", 40))
    ranked = job_fit.rank_companies(companies, config)

    allowed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for row in ranked:
        email = row.get("email") or row.get("primary_email", "")
        source = row.get("email_source") or row.get("source", "")
        verified = bool(row.get("email_verified"))
        score = row.get("job_fit_score", 0)
        tier = classify_email(email, source, verified=verified)

        if score < min_fit:
            row = {**row, "skip_reason": f"ملاءمة {score}% < {min_fit}%"}
            skipped.append(row)
            continue
        if not is_auto_send_allowed(email, source, config, verified=verified):
            row = {**row, "skip_reason": f"إيميل {tier}: {email}"}
            skipped.append(row)
            continue
        row = {**row, "email_tier": tier}
        allowed.append(row)

    if not cfg.get("prioritize_by_fit", True):
        return allowed, skipped
    return allowed, skipped


def promote_hr_primary(company_id: int) -> bool:
    """Set best HR email as primary when available."""
    emails = db.get_company_emails(company_id)
    if not emails:
        return False

    def _rank(e: dict[str, Any]) -> tuple[int, int]:
        local = email_local_part(e["email"])
        source = e.get("source", "")
        tier = classify_email(e["email"], source, verified=bool(e.get("verified")))
        tier_score = {"hr": 0, "verified": 1, "ok": 2, "weak": 3, "blocked": 4}.get(tier, 5)
        return tier_score, 0 if e.get("is_primary") else 1

    best = min(emails, key=_rank)
    if best.get("is_primary"):
        return classify_email(best["email"], best.get("source", ""), verified=bool(best.get("verified"))) == "hr"
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE emails SET is_primary = 0 WHERE company_id = ?",
            (company_id,),
        )
        conn.execute(
            "UPDATE emails SET is_primary = 1 WHERE id = ?",
            (best["id"],),
        )
    return classify_email(best["email"], best.get("source", ""), verified=bool(best.get("verified"))) in ("hr", "verified")


def promote_all_hr_emails() -> int:
    count = 0
    for company in db.get_companies():
        if promote_hr_primary(company["id"]):
            count += 1
    return count


def _recent_whatsapp_ids(days: int = 7) -> set[int]:
    if days <= 0:
        return set()
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    ids: set[int] = set()
    for row in db.get_whatsapp_log(500):
        if (row.get("created_at") or "")[:10] >= cutoff:
            ids.add(row["company_id"])
    return ids


def get_whatsapp_followup_targets(
    config: Optional[dict[str, Any]] = None,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Top sent companies with phone — for WhatsApp follow-up after email."""
    config = config or load_config()
    cfg = quality_settings(config)
    limit = limit or int(cfg.get("whatsapp_followup_top", 30))
    min_fit = int(cfg.get("whatsapp_min_fit", 50))
    cities = config.get("automation", {}).get("target_cities")
    recent = _recent_whatsapp_ids(int(cfg.get("whatsapp_skip_recent_days", 7)))

    targets: list[dict[str, Any]] = []
    for sent in db.get_sent_companies(limit=500):
        cid = sent.get("company_id")
        if cid in recent:
            continue
        company = db.get_company(cid)
        if not company or not company.get("phone"):
            continue
        if cities and company.get("city") not in cities:
            continue
        row = {**company, **sent}
        row["email"] = sent.get("email") or company.get("primary_email")
        targets.append(row)

    ranked = job_fit.rank_companies(targets, config)
    return [r for r in ranked if r.get("job_fit_score", 0) >= min_fit][:limit]
