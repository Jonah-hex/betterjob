"""Smart job application strategy — tiers, quotas, customization, follow-ups."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import yaml

import database as db
import job_fit
import outreach_quality
import strategy_store

BASE_DIR = __file__.replace("application_strategy.py", "")


def load_config(path: str = "config.yaml") -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _strategy_cfg(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("application_strategy", {})


def _company_text(company: dict[str, Any]) -> str:
    return " ".join(
        str(company.get(k, "") or "")
        for k in ("company_name", "sector", "website", "notes", "city", "primary_email", "email")
    ).lower()


def _is_priority_employer(company: dict[str, Any], config: dict[str, Any]) -> bool:
    text = _company_text(company)
    for emp in config.get("job_discovery", {}).get("priority_employers", []):
        needles = [str(emp.get("name", "")).lower()]
        needles.extend(str(k).lower() for k in emp.get("keywords", []))
        if any(n and n in text for n in needles):
            return True
    return False


def _matches_keywords(text: str, keywords: list[str]) -> bool:
    return any(kw.lower() in text for kw in keywords)


def _job_title_by_rank(config: dict[str, Any], rank: int) -> dict[str, str]:
    titles = config.get("job_discovery", {}).get("target_job_titles", [])
    for item in titles:
        if int(item.get("rank", 0)) == rank:
            return {
                "title_en": item.get("title_en", "Senior Land Surveyor"),
                "title_ar": item.get("title_ar", "مساح أراضي أول"),
            }
    profile = config.get("profile", {})
    return {
        "title_en": profile.get("apply_as_titles", [profile.get("title", "General Land Surveyor")])[0],
        "title_ar": profile.get("title_ar", "مساح عام"),
    }


def _job_rank_for_title(config: dict[str, Any], title_en: str) -> int:
    titles = config.get("job_discovery", {}).get("target_job_titles", [])
    key = title_en.split("/")[0].strip().lower()
    for item in titles:
        if key in item.get("title_en", "").lower():
            return int(item.get("rank", 10))
    return 10


def get_customization_plan(
    company: dict[str, Any],
    config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Minutes and instructions based on job rank (1-3 deep, 4-6 medium, 7+ light)."""
    config = config or load_config()
    meta = classify_tier(company, config)
    rank = meta.get("job_rank") or _job_rank_for_title(config, meta["job_title_en"])
    tiers = _strategy_cfg(config).get("customization_time", {})

    for level in ("deep", "medium", "light"):
        block = tiers.get(level, {})
        if rank in block.get("job_ranks", []):
            return {
                "level": level,
                "label_ar": block.get("label_ar", level),
                "minutes": int(block.get("minutes", 5)),
                "job_rank": rank,
                "require_project_mention": bool(block.get("require_project_mention")),
                "instruction_ar": block.get("instruction_ar", ""),
            }

    light = tiers.get("light", {})
    return {
        "level": "light",
        "label_ar": light.get("label_ar", "تخصيص سريع"),
        "minutes": int(light.get("minutes", 5)),
        "job_rank": rank,
        "require_project_mention": False,
        "instruction_ar": light.get("instruction_ar", ""),
    }


def suggest_project_line(company: dict[str, Any], config: Optional[dict[str, Any]] = None) -> dict[str, str]:
    """Editable draft mentioning company + city (replace with real project after research)."""
    config = config or load_config()
    name = company.get("company_name", "شركتكم")
    city = company.get("city") or config.get("profile", {}).get("city", "Jeddah")
    sector = company.get("sector") or "construction"
    return {
        "ar": (
            f"أتابع مشاريع {name} في {city}، و أرى أن خبرتي في المساحة الإنشائية "
            f"و{sector} قد تدعم فريقكم — especially setting out and as-built deliverables."
        ),
        "en": (
            f"I have been following {name}'s projects in {city}, and I believe my "
            f"construction surveying experience ({sector}) aligns with your field teams."
        ),
    }


def classify_tier(company: dict[str, Any], config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Return tier id, job title, hook key for a company."""
    config = config or load_config()
    rules = _strategy_cfg(config).get("tier_rules", {})
    text = _company_text(company)
    fit = company.get("job_fit_score") or job_fit.score_company(company, config)

    if _is_priority_employer(company, config):
        rule = rules.get("priority_employers", {})
        rank = int(rule.get("job_title_rank", 1))
        titles = _job_title_by_rank(config, rank)
        return {
            "tier": "priority_employers",
            "tier_label_ar": "شركة أولوية",
            "job_title_en": titles["title_en"],
            "job_title_ar": titles["title_ar"],
            "job_rank": rank,
            "hook_key": rule.get("hook", "priority"),
            "fit_score": fit,
        }

    for tier_id, key in (
        ("overlooked_gis", "overlooked_gis"),
        ("overlooked_cadastral", "overlooked_cadastral"),
        ("overlooked_inspector", "overlooked_inspector"),
    ):
        rule = rules.get(key, {})
        if _matches_keywords(text, rule.get("keywords", [])):
            rank = int(rule.get("job_title_rank", 5))
            titles = _job_title_by_rank(config, rank)
            return {
                "tier": key,
                "tier_label_ar": "وظيفة مغفولة",
                "job_title_en": titles["title_en"],
                "job_title_ar": titles["title_ar"],
                "job_rank": rank,
                "hook_key": rule.get("hook", key),
                "fit_score": fit,
            }

    senior_rule = rules.get("senior", {})
    if fit >= int(senior_rule.get("min_fit_score", 65)):
        rank = int(senior_rule.get("job_title_rank", 1))
        titles = _job_title_by_rank(config, rank)
        return {
            "tier": "senior_roles",
            "tier_label_ar": "Senior Land Surveyor",
            "job_title_en": titles["title_en"],
            "job_title_ar": titles["title_ar"],
            "job_rank": rank,
            "hook_key": senior_rule.get("hook", "senior"),
            "fit_score": fit,
        }

    std = rules.get("standard", {})
    rank = int(std.get("job_title_rank", 2))
    titles = _job_title_by_rank(config, rank)
    return {
        "tier": "standard",
        "tier_label_ar": "تقديم قياسي",
        "job_title_en": titles["title_en"],
        "job_title_ar": titles["title_ar"],
        "job_rank": rank,
        "hook_key": std.get("hook", "standard"),
        "fit_score": fit,
    }


def get_hook(hook_key: str, config: Optional[dict[str, Any]] = None) -> dict[str, str]:
    config = config or load_config()
    hooks = _strategy_cfg(config).get("achievement_hooks", {})
    hook = hooks.get(hook_key, hooks.get("standard", {}))
    return {"ar": hook.get("ar", ""), "en": hook.get("en", "")}


def build_subject(company: dict[str, Any], config: Optional[dict[str, Any]] = None) -> str:
    config = config or load_config()
    profile = config["profile"]
    meta = classify_tier(company, config)
    title_short = meta["job_title_en"].split("/")[0].strip()
    subject = (
        f"Application — {title_short} | {profile['years_experience']} yrs | "
        f"{profile['full_name']}"
    )
    return subject[:78]


def get_today_focus(config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    config = config or load_config()
    strat = _strategy_cfg(config)
    weekday = datetime.now().weekday()
    keys = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    day_key = keys[weekday]
    plan = strat.get("weekly_plan", {}).get(day_key, {})
    daily = strat.get("daily_targets", {})
    return {
        "day_key": day_key,
        "label_ar": plan.get("label_ar", day_key),
        "focus": plan.get("focus", "mixed"),
        "new_target": plan.get("new_applications", daily.get("total", 3)),
        "follow_up_target": plan.get("follow_ups", 2),
        "is_review_day": plan.get("focus") in ("rest", "research", "review", "prepare"),
        "is_rest_day": plan.get("focus") == "rest",
        "is_research_day": plan.get("focus") == "research",
    }


def get_quota_status(config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    config = config or load_config()
    strat = _strategy_cfg(config)
    daily = strat.get("daily_targets", {})
    weekly = strat.get("weekly_targets", {})
    focus = get_today_focus(config)

    tier_keys = ("priority_employers", "senior_roles", "overlooked_gis", "overlooked_cadastral", "overlooked_inspector", "standard")
    today_by_tier = {t: strategy_store.count_by_tier_on_date(t) for t in tier_keys}
    overlooked_today = (
        today_by_tier["overlooked_gis"]
        + today_by_tier["overlooked_cadastral"]
        + today_by_tier["overlooked_inspector"]
    )

    return {
        "today": {
            "total_sent": strategy_store.count_applications_on_date(),
            "total_target": focus["new_target"] if focus["new_target"] else daily.get("total", 3),
            "priority_sent": today_by_tier["priority_employers"],
            "priority_target": daily.get("priority_employers", 2),
            "senior_sent": today_by_tier["senior_roles"],
            "senior_target": daily.get("senior_roles", 4),
            "overlooked_sent": overlooked_today,
            "overlooked_target": daily.get("overlooked_roles", 2),
            "standard_sent": today_by_tier["standard"],
            "standard_target": daily.get("standard", 2),
        },
        "week": {
            "applications_sent": strategy_store.get_strategy_stats()["week_applications"],
            "applications_target": weekly.get("new_applications", 15),
            "priority_sent": strategy_store.count_by_tier_in_week("priority_employers"),
            "priority_target": weekly.get("priority_employers", 10),
            "follow_ups_due": strategy_store.get_strategy_stats()["due_follow_ups"],
            "follow_ups_target": weekly.get("follow_ups", 15),
        },
        "focus": focus,
    }


def _tier_quota_remaining(tier: str, quotas: dict[str, Any]) -> int:
    today = quotas["today"]
    mapping = {
        "priority_employers": ("priority_sent", "priority_target"),
        "senior_roles": ("senior_sent", "senior_target"),
        "overlooked_gis": ("overlooked_sent", "overlooked_target"),
        "overlooked_cadastral": ("overlooked_sent", "overlooked_target"),
        "overlooked_inspector": ("overlooked_sent", "overlooked_target"),
        "standard": ("standard_sent", "standard_target"),
    }
    sent_key, target_key = mapping.get(tier, ("total_sent", "total_target"))
    return max(0, today[target_key] - today[sent_key])


def _focus_allows_tier(focus: str, tier: str) -> bool:
    if focus in ("mixed", "review", "prepare"):
        return True
    if focus == "priority_employers":
        return tier == "priority_employers"
    if focus == "senior_roles":
        return tier in ("priority_employers", "senior_roles")
    if focus == "overlooked_roles":
        return tier.startswith("overlooked")
    if focus == "standard":
        return tier in ("standard", "senior_roles")
    return True


def build_research_preview(
    config: Optional[dict[str, Any]] = None,
    limit: int = 15,
) -> list[dict[str, Any]]:
    """Saturday: preview up to 15 companies to research and pre-edit messages."""
    config = config or load_config()
    cities = config.get("automation", {}).get("target_cities", [])
    raw = db.get_sendable_companies(cities)
    sendable, _ = outreach_quality.prioritize_sendable(raw, config)
    preview: list[dict[str, Any]] = []
    for company in sendable:
        cid = company.get("id") or company.get("company_id")
        if not cid or strategy_store.get_application_for_company(cid):
            continue
        meta = classify_tier(company, config)
        row = dict(company)
        row.update(meta)
        row["customization"] = get_customization_plan(row, config)
        row["project_draft"] = suggest_project_line(row, config)
        preview.append(row)
        if len(preview) >= limit:
            break
    return preview


def build_today_queue(
    config: Optional[dict[str, Any]] = None,
    cities: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Ranked list of companies to apply today respecting strategy quotas."""
    config = config or load_config()
    if not _strategy_cfg(config).get("enabled", True):
        return []

    focus = get_today_focus(config)
    if focus.get("is_review_day"):
        return []

    quotas = get_quota_status(config)
    cities = cities or config.get("automation", {}).get("target_cities", [])
    raw = db.get_sendable_companies(cities)
    sendable, _skipped = outreach_quality.prioritize_sendable(raw, config)

    queue: list[dict[str, Any]] = []
    used_ids: set[int] = set()

    for company in sendable:
        cid = company.get("id") or company.get("company_id")
        if not cid or cid in used_ids:
            continue
        if strategy_store.get_application_for_company(cid):
            continue

        meta = classify_tier(company, config)
        tier = meta["tier"]
        if not _focus_allows_tier(focus["focus"], tier):
            continue
        if _tier_quota_remaining(tier, quotas) <= 0 and tier != "priority_employers":
            if _tier_quota_remaining("priority_employers", quotas) <= 0:
                continue

        row = dict(company)
        row.update(meta)
        row["customization"] = get_customization_plan(row, config)
        row["subject_preview"] = build_subject(row, config)
        row["hook"] = get_hook(meta["hook_key"], config)
        queue.append(row)
        used_ids.add(cid)

        if len(queue) >= quotas["today"]["total_target"]:
            break

    queue.sort(
        key=lambda x: (
            0 if x["tier"] == "priority_employers" else 1,
            -(x.get("fit_score") or 0),
        ),
    )
    return queue


def record_successful_application(
    company: dict[str, Any],
    outreach_log_id: Optional[int],
    subject: str,
    config: Optional[dict[str, Any]] = None,
) -> int:
    config = config or load_config()
    meta = classify_tier(company, config)
    stages = _strategy_cfg(config).get("follow_up", {}).get("stages", [])
    app_id = strategy_store.record_application(
        company_id=company["id"],
        outreach_log_id=outreach_log_id,
        job_title_en=meta["job_title_en"],
        job_title_ar=meta["job_title_ar"],
        tier=meta["tier"],
        hook_key=meta["hook_key"],
        subject=subject,
    )
    if stages:
        strategy_store.schedule_follow_ups(
            application_id=app_id,
            company_id=company["id"],
            applied_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            stages=stages,
        )
    return app_id


def compose_follow_up(
    follow_up: dict[str, Any],
    config: Optional[dict[str, Any]] = None,
) -> dict[str, str]:
    config = config or load_config()
    profile = config["profile"]
    company_name = follow_up.get("company_name", "")
    job_title = follow_up.get("job_title_en", "Senior Land Surveyor")
    stage = int(follow_up.get("stage", 1))
    channel = follow_up.get("channel", "email")

    if channel == "whatsapp":
        msg = (
            f"السلام عليكم،\n"
            f"تابعتُ طلبي لوظيفة {job_title} لدى {company_name} قبل أسبوع.\n"
            f"أرفقت سيرتي سابقاً — {profile['years_experience']} سنة خبرة مساحة.\n"
            f"هل يمكن مراجعة طلبي؟ {profile['phone']}"
        )
        return {"channel": "whatsapp", "body_ar": msg, "body_en": msg, "subject": ""}

    if stage >= 3:
        subject = f"Follow-up — {job_title} Application | {profile['full_name']}"
        body_ar = (
            f"السادة الكرام في {company_name}،\n\n"
            f"أتابع طلب التوظيف لوظيفة {job_title} الذي أرسلته مع سيرتي الذاتية.\n"
            f"ما زلت مهتماً بالانضمام لفريقكم. {get_hook('senior', config)['ar']}\n\n"
            f"شاكراً وقتكم،\n{profile['full_name_ar']}\n{profile['phone']}"
        )
        body_en = (
            f"Dear {company_name} Hiring Team,\n\n"
            f"I am following up on my application for {job_title} submitted with my CV.\n"
            f"I remain very interested. {get_hook('senior', config)['en']}\n\n"
            f"Thank you,\n{profile['full_name']}\n{profile['phone']}"
        )
    else:
        subject = f"Re: Application — {job_title} | {profile['full_name']}"
        body_ar = (
            f"السادة الكرام في {company_name}،\n\n"
            f"أود متابعة طلبي لوظيفة {job_title} المرسل قبل أيام مع السيرة الذاتية.\n"
            f"يسعدني تزويدكم بأي معلومات إضافية.\n\n"
            f"{profile['full_name_ar']} — {profile['phone']}"
        )
        body_en = (
            f"Dear {company_name} Team,\n\n"
            f"I hope to follow up on my recent application for {job_title} (CV attached previously).\n"
            f"Happy to provide any additional information.\n\n"
            f"{profile['full_name']} — {profile['phone']}"
        )

    return {
        "channel": "email",
        "subject": subject[:78],
        "body_ar": body_ar,
        "body_en": body_en,
    }


def strategy_summary_text(config: Optional[dict[str, Any]] = None) -> str:
    config = config or load_config()
    q = get_quota_status(config)
    f = q["focus"]
    t = q["today"]
    w = q["week"]
    lines = [
        f"📅 {f['label_ar']}",
        f"🎯 اليوم: {t['total_sent']}/{t['total_target']} (3×5=15/أسبوع)",
        f"📆 الأسبوع: {w['applications_sent']}/{w['applications_target']} | متابعات: {w['follow_ups_due']}",
    ]
    return "\n".join(lines)
