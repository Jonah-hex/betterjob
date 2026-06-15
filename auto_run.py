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
import send_email

load_dotenv()
BASE_DIR = Path(__file__).parent


def load_config() -> dict:
    with open(BASE_DIR / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


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


def run_sending(config: dict) -> dict:
    log("=== المرحلة 3: إرسال CV تلقائياً ===")
    dry = config.get("sending", {}).get("dry_run", False)
    if dry:
        log("  ⚠️ وضع dry-run مفعّل — لن يُرسل فعلياً")
    else:
        log("  📤 إرسال حقيقي مفعّل")

    result = send_email.auto_send_all(config)
    log(f"  تم الإرسال: {result['sent']} | فشل: {result['failed']} | متبقي اليوم: {result['remaining_today']}")

    for detail in result.get("details", []):
        icon = "✅" if detail.get("success") else "❌"
        company = detail.get("company", "")
        email = detail.get("email", "")
        err = detail.get("error", detail.get("message", ""))
        log(f"    {icon} {company} ({email}) {err}")

    return result


def run_prepare_sendable(config: dict) -> dict:
    """استخراج إيميلات + دومينات ثم تجهيز الشركات الجديدة للإرسال."""
    import delivery_tracking as tracking

    extract_result = run_extraction(config)
    import discover_domains
    domain_stats = discover_domains.enrich_all_pending(config)
    cities = config.get("automation", {}).get("target_cities")
    queue_stats = tracking.prepare_for_sending(cities)
    pending = db.get_sendable_companies(cities)
    return {
        "extract": extract_result,
        "domains": domain_stats,
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


def run_full_pipeline(config: dict) -> None:
    errors = check_prerequisites(config)
    if errors:
        log("❌ متطلبات ناقصة:")
        for e in errors:
            log(f"   - {e}")
        sys.exit(1)

    db.init_db()
    stats_before = db.get_stats()
    log(f"قاعدة البيانات: {stats_before.get('total', 0)} شركة")

    run_discovery(config)
    run_extraction(config)
    import discover_domains
    domain_stats = discover_domains.enrich_all_pending(config)
    log(f"  دومينات: إيميل مُستنتج {domain_stats.get('email_found', 0)}")
    run_sending(config)

    stats_after = db.get_stats()
    log("=== ملخص نهائي ===")
    log(f"  إجمالي الشركات: {stats_after.get('total', 0)}")
    log(f"  إيميل موجود: {stats_after.get('email_found', 0)}")
    log(f"  تم الإرسال: {stats_after.get('sent', 0)}")
    log(f"  بدون إيميل: {stats_after.get('no_email', 0)}")
    log(f"  مُرسل اليوم: {stats_after.get('sent_today', 0)}")
    log("✅ اكتمل التشغيل الآلي")


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
        run_full_pipeline(config)


if __name__ == "__main__":
    main()
