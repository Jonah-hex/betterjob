"""Check domain + Brevo setup readiness."""

from __future__ import annotations

import os
import re

import yaml
from dotenv import load_dotenv

load_dotenv()
BASE = os.path.dirname(__file__)


def check_domain_setup() -> list[dict[str, str]]:
    results = []

    with open(os.path.join(BASE, "config.yaml"), encoding="utf-8") as f:
        config = yaml.safe_load(f)

    sender = config.get("profile", {}).get("sender_email", "")
    domain_cfg = config.get("domain", {})
    domain_name = domain_cfg.get("name", "")

    free_domains = ("hotmail.com", "gmail.com", "outlook.com", "yahoo.com", "live.com")
    sender_domain = sender.split("@")[-1].lower() if "@" in sender else ""

    if sender_domain in free_domains:
        results.append({
            "status": "error",
            "item": "المرسل",
            "message": f"لا يزال بريد مجاني: {sender} — غيّره لـ jobs@{domain_name}",
        })
    else:
        results.append({
            "status": "ok",
            "item": "المرسل",
            "message": f"بريد احترافي: {sender}",
        })

    smtp_login = os.getenv("SMTP_LOGIN") or os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    provider = os.getenv("EMAIL_PROVIDER", "")

    if not smtp_login or smtp_login.startswith("your_"):
        results.append({
            "status": "error",
            "item": "SMTP Login",
            "message": "SMTP_LOGIN غير مضبوط — انسخه من Brevo → SMTP & API",
        })
    elif "@smtp-brevo.com" in smtp_login or provider == "brevo_smtp":
        results.append({
            "status": "ok",
            "item": "SMTP Login",
            "message": f"Brevo login: {smtp_login}",
        })
    else:
        results.append({
            "status": "warn",
            "item": "SMTP Login",
            "message": f"تحقق أن Login صحيح: {smtp_login}",
        })

    if not smtp_pass or smtp_pass.startswith("your_"):
        results.append({
            "status": "error",
            "item": "SMTP Key",
            "message": "SMTP_PASSWORD غير مضبوط",
        })
    else:
        results.append({"status": "ok", "item": "SMTP Key", "message": "مفتاح SMTP موجود"})

    if domain_name and sender_domain == domain_name:
        results.append({
            "status": "ok",
            "item": "الدومين",
            "message": f"الدومين متطابق: {domain_name}",
        })
    elif domain_name:
        results.append({
            "status": "warn",
            "item": "الدومين",
            "message": f"تأكد من مصادقة {domain_name} في Brevo",
        })

    return results


if __name__ == "__main__":
    icons = {"ok": "✅", "warn": "⚠️", "error": "❌"}
    print("=== فحص إعداد الدومين ===\n")
    for r in check_domain_setup():
        print(f"{icons.get(r['status'], '?')} {r['item']}: {r['message']}")
