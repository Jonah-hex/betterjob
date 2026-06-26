"""Outreach quality — prioritize by fit, filter weak emails, WhatsApp follow-up targets."""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlparse

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
    "gulftalent",
    "naukrigulf",
    "ejobsboard",
    "tanqeeb",
    "glassdoor",
    "monster",
    "ziprecruiter",
    "careers-ksa",
    "homerun",
    "gethomerun",
    "jobrapido",
    "neuvoo",
    "jooble",
)

SKIP_WEBSITE_HOST_FRAGMENTS = SKIP_EMAIL_DOMAIN_FRAGMENTS

INFERRED_DISCOVERY_SOURCES = frozenset({
    "directory",
    "linkedin",
    "careers_portal",
    "deep_search",
})

LISTING_NAME_FRAGMENTS = (
    "top 10",
    "top 21",
    "top 27",
    "top 40",
    "top construction",
    "best 40",
    "best construction",
    "list of",
    "meet the builder",
    "emails & contacts",
    "email & contacts",
    "business directory",
    "company profile",
    "contact details",
    "construction companies in",
    "engineering companies in",
    "construction jeddah -",
    " - expatriates",
    "أفضل 40",
    "أفضل 10",
    "قائمة ",
    "فرص عمل",
    "مطلوب مقاولات",
    "دليل الأعمال",
    "gulfnear",
    "ksaexpats",
    "saudiayp",
    "eyeofriyadh",
    "mourjan.com",
    "bizmideast",
    "gulfleads",
    "gludo.org",
    "expatriates.com",
    "price-ksa",
    "dalilmadina",
)

DEFAULT_EXCLUDE_COMPANY_FRAGMENTS = (
    "homerun",
    "gethomerun",
    "job at ",
    "jobs in ",
    "jobs at ",
    "job opening",
    "land surveyor job",
    "surveyor job",
    "surveyors jobs",
    "| jobs",
    "vacancy",
    "hiring now",
    "drone course",
    "course -",
    "training course",
    "gis mappers",
    "equipment dealer",
    "geomax",
    "chcnav",
    "service provider",
    "best 40",
    "top 40",
    "linkedin.com/jobs",
    "glassdoor.com",
    "gulftalent.com",
    "naukrigulf.com",
    "وظائف في",
    "وظيفة في",
    "دورة ",
    "كورس",
    "تدريب",
    "مزود خدمة",
    "yellowpages",
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


def _exclude_company_fragments(config: Optional[dict[str, Any]] = None) -> tuple[str, ...]:
    config = config or load_config()
    extra = config.get("outreach_quality", {}).get("exclude_company_patterns", [])
    merged = list(DEFAULT_EXCLUDE_COMPANY_FRAGMENTS) + [str(x).lower() for x in extra]
    return tuple(dict.fromkeys(merged))


def is_excluded_company(
    name: str,
    website: Optional[str] = None,
    job_url: Optional[str] = None,
    config: Optional[dict[str, Any]] = None,
) -> bool:
    """Job boards, HomeRun listings, courses — not hiring employers."""
    text = " ".join(
        part for part in (name or "", website or "", job_url or "") if part
    ).lower()
    if not text.strip():
        return True
    if any(frag in text for frag in _exclude_company_fragments(config)):
        return True
    if website:
        host = urlparse(website).netloc.lower().replace("www.", "")
        if any(frag in host for frag in SKIP_WEBSITE_HOST_FRAGMENTS):
            return True
    return False


def is_blocked_outreach_email(email: str, config: Optional[dict[str, Any]] = None) -> bool:
    """Never send CV to portal / listing addresses."""
    if not email or "@" not in email:
        return True
    if is_skip_email_domain(email):
        return True
    config = config or load_config()
    extra = config.get("outreach_quality", {}).get("exclude_email_domains", [])
    domain = _email_domain(email)
    for frag in extra:
        if frag.lower() in domain:
            return True
    return False


def is_listing_company(
    name: str,
    website: Optional[str] = None,
    job_url: Optional[str] = None,
    config: Optional[dict[str, Any]] = None,
) -> bool:
    """Web directory / SEO list pages — not a hiring employer."""
    if is_excluded_company(name, website, job_url, config):
        return True
    text = " ".join(
        part for part in (name or "", website or "", job_url or "") if part
    ).lower()
    return any(frag in text for frag in LISTING_NAME_FRAGMENTS)


def _company_sent_successfully(conn, company_id: int) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM outreach_log
        WHERE company_id = ? AND dry_run = 0 AND error_message IS NULL
        LIMIT 1
        """,
        (company_id,),
    ).fetchone()
    return row is not None


def _company_email_sources(conn, company_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT source FROM emails WHERE company_id = ?",
        (company_id,),
    ).fetchall()
    return [r["source"] for r in rows]


def purge_directory_listings(config: Optional[dict[str, Any]] = None) -> dict[str, int]:
    """
    حذف شركات القوائم/الدليل وإيميلاتها المُستنتجة.
    يحتفظ بالشركات التي وصلها CV فعلياً (سجل إرسال ناجح).
    """
    config = config or load_config()
    stats = {
        "emails_removed": 0,
        "companies_deleted": 0,
        "companies_demoted": 0,
        "kept_sent": 0,
    }

    with db.get_connection() as conn:
        companies = conn.execute(
            """
            SELECT id, company_name, website, linkedin_url, careers_url, job_url,
                   discovery_source, status
            FROM companies
            """
        ).fetchall()

        for row in companies:
            cid = row["id"]
            if _company_sent_successfully(conn, cid):
                stats["kept_sent"] += 1
                continue

            sources = _company_email_sources(conn, cid)
            listing = is_listing_company(
                row["company_name"],
                row["website"],
                row["job_url"] or row["careers_url"] or row["linkedin_url"],
                config,
            )
            from_directory = row["discovery_source"] in INFERRED_DISCOVERY_SOURCES
            only_inferred = bool(sources) and all(s in INFERRED_SOURCES for s in sources)
            no_verified_email = not any(s in VERIFIED_SOURCES for s in sources)

            should_delete = (
                from_directory
                or listing
                or (only_inferred and no_verified_email)
            )

            if should_delete:
                conn.execute("DELETE FROM companies WHERE id = ?", (cid,))
                stats["companies_deleted"] += 1
                continue

            # إزالة إيميلات مُستنتجة من شركات حقيقية لم تُرسل بعد
            inferred_rows = conn.execute(
                """
                SELECT id FROM emails
                WHERE company_id = ? AND source IN ({})
                """.format(",".join("?" * len(INFERRED_SOURCES))),
                (cid, *INFERRED_SOURCES),
            ).fetchall()
            for email_row in inferred_rows:
                conn.execute("DELETE FROM emails WHERE id = ?", (email_row["id"],))
                stats["emails_removed"] += 1

            has_primary = conn.execute(
                """
                SELECT 1 FROM emails
                WHERE company_id = ? AND is_primary = 1
                LIMIT 1
                """,
                (cid,),
            ).fetchone()
            has_any = conn.execute(
                "SELECT 1 FROM emails WHERE company_id = ? LIMIT 1",
                (cid,),
            ).fetchone()

            if not has_any:
                conn.execute(
                    "UPDATE companies SET status = 'no_email' WHERE id = ?",
                    (cid,),
                )
                stats["companies_demoted"] += 1
            elif not has_primary and has_any:
                first = conn.execute(
                    "SELECT id FROM emails WHERE company_id = ? ORDER BY id LIMIT 1",
                    (cid,),
                ).fetchone()
                if first:
                    conn.execute(
                        "UPDATE emails SET is_primary = 1 WHERE id = ?",
                        (first["id"],),
                    )
                conn.execute(
                    "UPDATE companies SET status = 'no_email' WHERE id = ?",
                    (cid,),
                )
                stats["companies_demoted"] += 1

    return stats


def purge_all_non_employers(config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """تنظيف كامل: بوابات + قوائم/دليل."""
    config = config or load_config()
    portals = purge_non_employer_targets(config)
    listings = purge_directory_listings(config)
    return {"portals": portals, "listings": listings}


def classify_email(
    email: str,
    source: str,
    verified: bool = False,
    config: Optional[dict[str, Any]] = None,
) -> str:
    """
    Tier: hr | verified | ok | weak | blocked
    """
    if not email or "@" not in email:
        return "blocked"
    if source == "guessed" or is_blocked_outreach_email(email, config):
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
    tier = classify_email(email, source, verified=verified, config=config)
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
        tier = classify_email(email, source, verified=verified, config=config)

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


def purge_non_employer_targets(config: Optional[dict[str, Any]] = None) -> dict[str, int]:
    """
    Remove portal/listing emails and demote non-employer companies (HomeRun, job boards).
  Does not delete companies that already received a successful send.
    """
    config = config or load_config()
    stats = {
        "emails_removed": 0,
        "companies_demoted": 0,
        "sources_cleared": 0,
    }
    portal_sources = ("linkedin", "careers_portal", "deep_search")

    with db.get_connection() as conn:
        email_rows = conn.execute(
            "SELECT id, company_id, email FROM emails"
        ).fetchall()
        for row in email_rows:
            if is_blocked_outreach_email(row["email"], config):
                conn.execute("DELETE FROM emails WHERE id = ?", (row["id"],))
                stats["emails_removed"] += 1

        companies = conn.execute(
            "SELECT id, company_name, website, linkedin_url, careers_url, job_url, "
            "discovery_source, status FROM companies"
        ).fetchall()
        for row in companies:
            cid = row["id"]
            sent_ok = conn.execute(
                """
                SELECT 1 FROM outreach_log
                WHERE company_id = ? AND dry_run = 0 AND error_message IS NULL
                LIMIT 1
                """,
                (cid,),
            ).fetchone()
            if sent_ok:
                continue

            excluded = is_excluded_company(
                row["company_name"],
                row["website"],
                row["job_url"] or row["careers_url"] or row["linkedin_url"],
                config,
            )
            portal_source = row["discovery_source"] in portal_sources
            has_email = conn.execute(
                "SELECT 1 FROM emails WHERE company_id = ? LIMIT 1", (cid,)
            ).fetchone()

            if excluded or (portal_source and not has_email):
                conn.execute(
                    "DELETE FROM emails WHERE company_id = ?", (cid,)
                )
                conn.execute(
                    "UPDATE companies SET status = 'no_email' WHERE id = ?",
                    (cid,),
                )
                stats["companies_demoted"] += 1
                if portal_source:
                    stats["sources_cleared"] += 1
            elif portal_source or excluded:
                conn.execute(
                    "UPDATE companies SET status = 'no_email' WHERE id = ?",
                    (cid,),
                )
                stats["companies_demoted"] += 1

        # companies left without primary email
        for row in conn.execute(
            """
            SELECT c.id FROM companies c
            WHERE c.status IN ('email_found', 'approved')
            AND NOT EXISTS (
                SELECT 1 FROM emails e
                WHERE e.company_id = c.id AND e.is_primary = 1
            )
            """
        ).fetchall():
            conn.execute(
                "UPDATE companies SET status = 'no_email' WHERE id = ?",
                (row["id"],),
            )
            stats["companies_demoted"] += 1

    return stats
