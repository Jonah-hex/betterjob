"""
BetterJob — تشغيل آلي كامل
اكتشاف شركات جدة وأبها → استخراج إيميلات → إرسال CV تلقائياً

Usage:
    python auto_run.py
    python auto_run.py --discover-only
    python auto_run.py --send-only
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

import database as db
import discover_multi
import extract_email
import import_csv
import outreach_quality
import send_email

load_dotenv()
BASE_DIR = Path(__file__).parent

PIPELINE_STEPS = (
    ("discover", "① اكتشاف شامل"),
    ("extract", "② استخراج إيميلات"),
    ("domains", "③ استنتاج hr@ / careers@"),
    ("fit", "④ تقييم الملاءمة"),
    ("queue", "⑤ تجهيز الطابور"),
    ("send", "⑥ إرسال CV"),
)


def load_config() -> dict:
    with open(BASE_DIR / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _safe_text(text: object) -> str:
    if text is None:
        return ""
    if isinstance(text, bytes):
        return text.decode("utf-8", errors="replace")
    return str(text).encode("utf-8", errors="replace").decode("utf-8")


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {_safe_text(msg)}"
    try:
        print(line)
    except (OSError, UnicodeEncodeError):
        sys.stdout.buffer.write((line + "\n").encode("utf-8", errors="replace"))
        sys.stdout.buffer.flush()


def check_prerequisites(config: dict) -> list[str]:
    errors = []
    provider = config.get("discovery_provider", "overpass")

    if provider == "google":
        api_key = os.getenv("GOOGLE_PLACES_API_KEY", "")
        if not api_key or api_key.startswith("your_"):
            errors.append("GOOGLE_PLACES_API_KEY غير موجود — أو غيّر discovery_provider في config.yaml")

    if provider == "csv":
        csv_path = BASE_DIR / "data" / "companies.csv"
        if not csv_path.exists():
            errors.append(f"أنشئ ملف {csv_path} من companies_template.csv")

    if not config.get("sending", {}).get("dry_run", False):
        email_provider = os.getenv("EMAIL_PROVIDER", "smtp").lower()
        if email_provider == "smtp":
            pwd = os.getenv("SMTP_PASSWORD", "")
            if not os.getenv("SMTP_USER") or not pwd or pwd.startswith("your_"):
                errors.append(
                    "SMTP_PASSWORD غير مضبوط — استخدم Brevo (مجاني) أو ضع SMTP key في .env"
                )
        elif email_provider == "brevo_api":
            if not os.getenv("BREVO_API_KEY") or os.getenv("BREVO_API_KEY", "").startswith("your_"):
                errors.append("BREVO_API_KEY غير موجود في .env")
        elif provider == "gmail":
            if not (BASE_DIR / "credentials.json").exists():
                errors.append("credentials.json غير موجود لـ Gmail OAuth")
    cv_pdf = BASE_DIR / "assets" / "cv" / "cv.pdf"
    if not cv_pdf.exists():
        errors.append("assets/cv/cv.pdf غير موجود")
    return errors


def run_discovery(config: dict) -> dict:
    log("=== المرحلة 1: اكتشاف الشركات (جدة + أبها) ===")
    provider = config.get("discovery_provider", "overpass")
    log(f"  المصدر: {provider}")

    if provider == "google":
        results = discover_multi.discover_all_sources(config)
        results = results.get("by_source", {}).get("google", {})
        if not isinstance(results, dict) or "new" not in str(results):
            import discover
            results = discover.discover_target_cities(config)
    elif provider == "csv":
        csv_path = BASE_DIR / "data" / "companies.csv"
        stats = import_csv.import_csv(csv_path)
        results = {"CSV": stats}
        log(f"  مستورد: {stats['imported']} | بإيميل: {stats['with_email']}")
    elif provider == "overpass":
        import discover_overpass
        results = discover_overpass.discover_target_cities(config)
    elif provider == "multi":
        summary = discover_multi.discover_all_sources(config)
        results = discover_multi.discover_target_cities(config)
        log(f"  المصادر: {', '.join(summary.get('sources_run', []))}")
    else:
        results = discover_multi.discover_target_cities(config)

    total_new = sum(r.get("new", 0) for r in results.values())
    for city, stats in results.items():
        log(f"  {city}: جديد {stats.get('new', 0)} | محدّث {stats.get('updated', 0)} | متجاهل {stats.get('skipped', 0)}")
        for err in stats.get("errors", []):
            log(f"    ⚠️ {err}")
    log(f"  الإجمالي: {total_new} شركة جديدة")
    return results


def run_extraction(config: dict) -> dict:
    log("=== المرحلة 2: استخراج الإيميلات ===")
    result = extract_email.extract_all_pending(config)
    log(f"  معالجة: {result['processed']} | إيميل وُجد: {result['email_found']} | بدون إيميل: {result['no_email']}")
    return result


def run_sending(config: dict, on_progress=None) -> dict:
    log("=== المرحلة 3: إرسال CV تلقائياً ===")
    dry = config.get("sending", {}).get("dry_run", False)
    if dry:
        log("  ⚠️ وضع dry-run مفعّل — لن يُرسل فعلياً")
    else:
        log("  📤 إرسال حقيقي مفعّل")

    result = send_email.auto_send_all(config, on_progress=on_progress)
    log(f"  تم الإرسال: {result['sent']} | فشل: {result['failed']} | متبقي اليوم: {result['remaining_today']}")

    for detail in result.get("details", []):
        icon = "✅" if detail.get("success") else "❌"
        company = detail.get("company", "")
        email = detail.get("email", "")
        err = _safe_text(detail.get("error", detail.get("message", "")))
        log(f"    {icon} {_safe_text(company)} ({_safe_text(email)}) {err}")

    return result


def run_prepare_sendable(config: dict) -> dict:
    """استخراج إيميلات + دومينات ثم تجهيز الشركات الجديدة للإرسال."""
    import delivery_tracking as tracking

    extract_result = run_extraction(config)
    import discover_domains
    import outreach_quality
    domain_stats = discover_domains.enrich_all_pending(config)
    hr_promoted = outreach_quality.promote_all_hr_emails()
    cities = config.get("automation", {}).get("target_cities")
    queue_stats = tracking.prepare_for_sending(cities)
    pending = db.get_sendable_companies(cities)
    return {
        "extract": extract_result,
        "domains": domain_stats,
        "hr_promoted": hr_promoted,
        "approved": queue_stats.get("approved", 0),
        "queued": queue_stats.get("queued", 0),
        "pending_count": len(pending),
    }


def run_apply_new(config: dict) -> dict:
    """تقديم CV لجميع الشركات الجديدة الجاهزة (ضمن الحد اليومي)."""
    prep = run_prepare_sendable(config)
    send_result = run_sending(config)
    return {**send_result, **prep}


def run_discover_and_apply(config: dict) -> dict:
    """اكتشاف شركات جديدة ثم تقديم CV عليها مباشرة."""
    discovery = run_discovery(config)
    apply_result = run_apply_new(config)
    apply_result["discovery"] = discovery
    return apply_result


def run_deep_discover_and_send(
    config: dict,
    on_progress=None,
) -> dict[str, object]:
    """اكتشاف عميق (LinkedIn · بوابات · HR) + استخراج + إرسال CV."""
    errors = check_prerequisites(config)
    if errors:
        return {"success": False, "errors": errors}

    import discover_deep
    import job_fit
    import outreach_quality

    total = 4
    _notify_progress(on_progress, 1, total, "① اكتشاف شامل + عميق")
    summary = discover_multi.discover_all_sources(config)
    deep = discover_deep.discover_target_cities(config)
    deep_new = sum(r.get("new", 0) for r in deep.values() if isinstance(r, dict))

    _notify_progress(on_progress, 2, total, "② استخراج إيميلات ومواقع")
    prep = run_prepare_sendable(config)

    _notify_progress(on_progress, 3, total, "③ تقييم الملاءمة")
    job_fit.sync_all_scores(config)

    _notify_progress(on_progress, 4, total, "④ إرسال CV (أعلى جودة أولاً)")

    def send_progress(i, total, msg):
        if on_progress:
            frac = 3 / total + i / total  # steps 1-3 done, step 4 in progress
            on_progress(4, 4, msg)

    send_result = run_sending(config, on_progress=send_progress)

    cities = config.get("automation", {}).get("target_cities")
    import delivery_tracking as tracking
    pipeline = tracking.get_pipeline_summary(cities)

    return {
        "success": True,
        "discovery": {
            "sources": summary.get("sources_run", []),
            "total_new": summary.get("total_new", 0) + deep_new,
            "deep": deep,
        },
        "prep": prep,
        "send": send_result,
        "pipeline": {
            "completed": pipeline["completed"],
            "not_sent": pipeline["not_sent"],
            "failed": pipeline["failed"],
        },
    }


def run_extract_contacts_export(config: dict) -> dict[str, object]:
    """استخراج إيميلات من المواقع + تجهيز جدول جهات الاتصال."""
    import discover_domains
    import export_contacts
    import job_fit
    import outreach_quality

    extract_result = run_extraction(config)
    domain_stats = discover_domains.enrich_all_pending(config)
    hr_promoted = outreach_quality.promote_all_hr_emails()
    job_fit.sync_all_scores(config)

    cities = config.get("automation", {}).get("target_cities")
    df = export_contacts.build_contacts_dataframe(config, cities=cities)
    df_with_email = export_contacts.build_contacts_dataframe(
        config, cities=cities, with_email_only=True
    )

    return {
        "success": True,
        "extract": extract_result,
        "domains": domain_stats,
        "hr_promoted": hr_promoted,
        "total": len(df),
        "with_email": len(df_with_email),
        "dataframe": df,
        "dataframe_email": df_with_email,
    }


def _notify_progress(
    callback,
    step: int,
    total: int,
    message: str,
) -> None:
    if callback:
        callback(step, total, message)
    log(message)


def run_full_pipeline(
    config: dict,
    on_progress=None,
) -> dict[str, object]:
    """
    تشغيل كامل — 6 مراحل متوافقة مع الاكتشاف العميق والملاءمة والطابور.
    يُرجع ملخصاً للواجهة بدلاً من الخروج عند الخطأ.
    """
    errors = check_prerequisites(config)
    if errors:
        return {"success": False, "errors": errors}

    import discover_domains
    import delivery_tracking as tracking
    import job_fit

    db.init_db()
    stats_before = db.get_stats()
    cities = config.get("automation", {}).get("target_cities")
    total_steps = len(PIPELINE_STEPS)
    summary: dict[str, object] = {
        "success": True,
        "errors": [],
        "stats_before": stats_before,
    }

    # ① اكتشاف
    _notify_progress(on_progress, 1, total_steps, "① اكتشاف شامل (CSV · Google · OSM · دليل · LinkedIn · بوابات)")
    discovery_summary = discover_multi.discover_all_sources(config)
    discovery_results = discovery_summary.get("by_source", {})
    total_new = discovery_summary.get("total_new", 0)
    summary["discovery"] = {
        "sources": discovery_summary.get("sources_run", []),
        "total_new": total_new,
        "by_source": discovery_results,
    }
    log(f"  مصادر: {', '.join(discovery_summary.get('sources_run', []))} | جديد: {total_new}")

    # ② استخراج
    _notify_progress(on_progress, 2, total_steps, "② استخراج إيميلات من المواقع")
    extract_result = run_extraction(config)
    summary["extract"] = extract_result

    # ③ دومينات
    _notify_progress(on_progress, 3, total_steps, "③ استنتاج إيميلات hr@ / careers@")
    domain_stats = discover_domains.enrich_all_pending(config)
    hr_promoted = outreach_quality.promote_all_hr_emails()
    summary["domains"] = {**domain_stats, "hr_promoted": hr_promoted}
    log(f"  دومينات: {domain_stats.get('email_found', 0)} | HR primary: {hr_promoted}")

    # ④ ملاءمة
    _notify_progress(on_progress, 4, total_steps, "④ تقييم ملاءمة الوظيفة")
    fit_count = job_fit.sync_all_scores(config)
    summary["fit"] = {"scored": fit_count}

    # ⑤ طابور
    _notify_progress(on_progress, 5, total_steps, "⑤ تجهيز طابور الإرسال")
    queue_stats = tracking.prepare_for_sending(cities)
    pending = db.get_sendable_companies(cities)
    summary["queue"] = {
        **queue_stats,
        "pending_count": len(pending),
    }

    # ⑥ إرسال
    _notify_progress(on_progress, 6, total_steps, "⑥ إرسال CV — بدء...")

    def send_progress(i, total, msg):
        if on_progress:
            on_progress(6, 6, msg)

    send_result = run_sending(config, on_progress=send_progress)
    summary["send"] = send_result

    stats_after = db.get_stats()
    pipeline = tracking.get_pipeline_summary(cities)
    summary["stats_after"] = stats_after
    summary["pipeline"] = {
        "completed": pipeline["completed"],
        "pending": pipeline["pending"],
        "not_sent": pipeline["not_sent"],
        "failed": pipeline["failed"],
        "no_email": pipeline["no_email"],
    }

    log("=== ملخص نهائي ===")
    log(f"  شركات: {stats_after.get('total', 0)} | تم الإرسال: {stats_after.get('sent_confirmed', 0)}")
    log(f"  جاهز: {pipeline['not_sent']} | فشل غير محلول: {pipeline['failed']}")
    log(f"  مُرسل اليوم: {stats_after.get('sent_today', 0)}")
    log("✅ اكتمل التشغيل الكامل")
    return summary


def run_full_pipeline_cli(config: dict) -> None:
    """CLI wrapper — exits on prerequisite errors."""
    result = run_full_pipeline(config)
    if not result.get("success"):
        log("❌ متطلبات ناقصة:")
        for e in result.get("errors", []):
            log(f"   - {e}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="BetterJob Auto Pipeline")
    parser.add_argument("--discover-only", action="store_true", help="اكتشاف فقط")
    parser.add_argument("--extract-only", action="store_true", help="استخراج إيميل فقط")
    parser.add_argument("--send-only", action="store_true", help="إرسال فقط")
    args = parser.parse_args()

    config = load_config()
    db.init_db()

    if args.discover_only:
        run_discovery(config)
    elif args.extract_only:
        run_extraction(config)
    elif args.send_only:
        run_sending(config)
    else:
        run_full_pipeline_cli(config)


if __name__ == "__main__":
    main()
