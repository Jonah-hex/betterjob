"""Send outreach emails via Gmail API (OAuth2) or SMTP with dry-run support."""

from __future__ import annotations

import base64
import html as html_module
import os
import smtplib
import time
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv

import httpx
import compose
import database as db
import delivery_tracking as tracking
import outreach_quality

BASE_DIR = Path(__file__).parent
ENV_PATH = BASE_DIR / ".env"


def _load_env() -> None:
    load_dotenv(ENV_PATH, override=True)


_load_env()


def load_config(path: str = "config.yaml") -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_cv_path() -> Path:
    """ATS-optimized CV used for email attachments."""
    return BASE_DIR / "assets" / "cv" / "cv.pdf"


def get_uploaded_cv_path() -> Path:
    """User-uploaded CV preserved separately."""
    return BASE_DIR / "assets" / "cv" / "cv_uploaded.pdf"


def attachment_display_name(path: Path | str, config: Optional[dict[str, Any]] = None) -> str:
    """Friendly attachment label for UI and email filenames."""
    p = Path(path) if isinstance(path, str) else path
    return _attachment_filename(p, config)


def _attachment_filename(path: Path, config: Optional[dict[str, Any]] = None) -> str:
    """Display filename in email attachments (disk path unchanged)."""
    cfg = config or load_config()
    custom = cfg.get("sending", {}).get("attachment_names", {})
    defaults = {
        "cv.pdf": "Moh. CV.pdf",
        "cv_uploaded.pdf": "Moh. CV Full.pdf",
    }
    return custom.get(path.name) or defaults.get(path.name) or path.name


def _resolve_attachments(config: dict[str, Any]) -> list[Path]:
    """Attach ATS cv.pdf and uploaded cv_uploaded.pdf when both exist."""
    paths: list[Path] = []

    ats_cv = get_cv_path()
    if ats_cv.exists() and ats_cv.stat().st_size > 0:
        paths.append(ats_cv)

    uploaded_cv = get_uploaded_cv_path()
    if uploaded_cv.exists() and uploaded_cv.stat().st_size > 0:
        paths.append(uploaded_cv)

    if paths:
        return paths

    for rel in config.get("sending", {}).get("attachments", []):
        p = BASE_DIR / rel
        if p.exists() and p.stat().st_size > 0:
            paths.append(p)
    return paths


def validate_cv_pdf(data: bytes) -> tuple[bool, str]:
    if not data:
        return False, "الملف فارغ"
    if not data.startswith(b"%PDF"):
        return False, "الملف ليس PDF صالح"
    if len(data) < 1024:
        return False, "حجم الملف صغير جداً"
    return True, "ok"


def save_cv_pdf(data: bytes, backup: bool = True) -> Path:
    ok, msg = validate_cv_pdf(data)
    if not ok:
        raise ValueError(msg)

    path = get_uploaded_cv_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    if backup and path.exists():
        backup_path = path.with_suffix(".uploaded.bak")
        backup_path.write_bytes(path.read_bytes())

    path.write_bytes(data)
    return path


def get_uploaded_cv_info() -> dict[str, Any]:
    path = get_uploaded_cv_path()
    if not path.exists():
        return {"exists": False, "path": str(path)}
    stat = path.stat()
    return {
        "exists": True,
        "path": str(path),
        "size_kb": stat.st_size // 1024,
        "modified": stat.st_mtime,
    }


def get_cv_info() -> dict[str, Any]:
    path = get_cv_path()
    if not path.exists():
        return {"exists": False, "path": str(path)}
    stat = path.stat()
    return {
        "exists": True,
        "path": str(path),
        "size_kb": stat.st_size // 1024,
        "modified": stat.st_mtime,
    }


def _smtp_credentials() -> tuple[str, str, str, int]:
    """Reload .env each call so Streamlit picks up latest settings."""
    _load_env()
    host = os.getenv("SMTP_HOST", "smtp-mail.outlook.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    login = (os.getenv("SMTP_LOGIN") or os.getenv("SMTP_USER", "")).strip()
    password = (os.getenv("SMTP_PASSWORD", "") or "").strip()
    return host, port, login, password


def _text_to_html_paragraphs(text: str) -> str:
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    if not blocks:
        blocks = [line.strip() for line in text.split("\n") if line.strip()]
    return "".join(
        f'<p style="margin: 0 0 1em 0;">{html_module.escape(b).replace(chr(10), "<br>")}</p>'
        for b in blocks
    )


def _build_email_bodies(body_ar: str, body_en: str) -> tuple[str, str]:
    body_text = f"{body_ar}\n\n---\n\n{body_en}"
    body_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;font-size:14px;line-height:1.6;">
<div dir="rtl" style="direction:rtl;text-align:right;font-family:Tahoma,Arial,sans-serif;padding:16px;">
{_text_to_html_paragraphs(body_ar)}
</div>
<hr style="border:none;border-top:1px solid #ccc;margin:24px 0;">
<div dir="ltr" style="direction:ltr;text-align:left;font-family:Arial,sans-serif;padding:16px;">
{_text_to_html_paragraphs(body_en)}
</div>
</body>
</html>"""
    return body_text, body_html


def _build_mime_message(
    to_email: str,
    subject: str,
    body_ar: str,
    body_en: str,
    from_email: str,
    from_name: str,
    attachments: list[Path],
    config: Optional[dict[str, Any]] = None,
) -> MIMEMultipart:
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email

    body_text, body_html = _build_email_bodies(body_ar, body_en)
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(body_text, "plain", "utf-8"))
    alt.attach(MIMEText(body_html, "html", "utf-8"))
    msg.attach(alt)

    for path in attachments:
        with open(path, "rb") as f:
            data = f.read()
        fname = _attachment_filename(path, config)
        part = MIMEApplication(data, _subtype="pdf", Name=fname)
        part.add_header("Content-Disposition", "attachment", filename=fname)
        msg.attach(part)

    return msg


def send_via_smtp(
    to_email: str,
    subject: str,
    body_ar: str,
    body_en: str,
    config: dict[str, Any],
    attachments: list[Path],
) -> str:
    host, port, smtp_login, password = _smtp_credentials()
    profile = config["profile"]
    from_email = profile.get("sender_email") or smtp_login

    if not smtp_login or not password:
        raise ValueError("SMTP_LOGIN و SMTP_PASSWORD مطلوبان في .env")

    msg = _build_mime_message(
        to_email,
        subject,
        body_ar,
        body_en,
        from_email,
        profile["full_name"],
        attachments,
        config,
    )

    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls()
        try:
            server.login(smtp_login, password)
        except smtplib.SMTPAuthenticationError as exc:
            raise ValueError(
                "فشل تسجيل الدخول SMTP — تأكد من SMTP_LOGIN في .env "
                "(من Brevo → Settings → SMTP & API → Login، مثل xxx@smtp-brevo.com)"
            ) from exc
        server.send_message(msg, from_addr=from_email, to_addrs=[to_email])

    return f"smtp-{int(time.time())}"


def send_via_gmail_api(
    to_email: str,
    subject: str,
    body_ar: str,
    body_en: str,
    config: dict[str, Any],
    attachments: list[Path],
) -> str:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
    creds_path = BASE_DIR / "credentials.json"
    token_path = BASE_DIR / "token.json"

    if not creds_path.exists():
        raise FileNotFoundError(
            "credentials.json غير موجود — راجع README لإعداد Gmail OAuth"
        )

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    profile = config["profile"]
    msg = _build_mime_message(
        to_email,
        subject,
        body_ar,
        body_en,
        profile["sender_email"],
        profile["full_name"],
        attachments,
        config,
    )

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service = build("gmail", "v1", credentials=creds)
    result = service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()
    return result.get("id", "gmail-sent")


def send_via_brevo_api(
    to_email: str,
    subject: str,
    body_ar: str,
    body_en: str,
    config: dict[str, Any],
    attachments: list[Path],
) -> str:
    import base64 as b64

    api_key = os.getenv("BREVO_API_KEY", "")
    if not api_key:
        raise ValueError("BREVO_API_KEY غير موجود في .env")

    profile = config["profile"]
    body_text, body_html = _build_email_bodies(body_ar, body_en)

    att_payload = []
    for path in attachments:
        with open(path, "rb") as f:
            att_payload.append({
                "name": _attachment_filename(path, config),
                "content": b64.b64encode(f.read()).decode(),
            })

    payload = {
        "sender": {"name": profile["full_name"], "email": profile["sender_email"]},
        "to": [{"email": to_email}],
        "subject": subject,
        "textContent": body_text,
        "htmlContent": body_html,
    }
    if att_payload:
        payload["attachment"] = att_payload

    with httpx.Client(timeout=60) as client:
        response = client.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": api_key, "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    return data.get("messageId", f"brevo-{int(time.time())}")


def _dispatch_send(
    to_email: str,
    subject: str,
    body_ar: str,
    body_en: str,
    config: dict[str, Any],
    attachments: list[Path],
) -> str:
    provider = os.getenv("EMAIL_PROVIDER", "smtp").lower()
    if provider == "gmail":
        return send_via_gmail_api(to_email, subject, body_ar, body_en, config, attachments)
    if provider == "brevo_api":
        return send_via_brevo_api(to_email, subject, body_ar, body_en, config, attachments)
    return send_via_smtp(to_email, subject, body_ar, body_en, config, attachments)


def send_test_email(
    to_email: str,
    config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Send a real test email with current cv.pdf attached."""
    config = config or load_config()
    attachments = _resolve_attachments(config)
    if not attachments:
        return {"success": False, "error": "cv.pdf غير موجود — ولّد ATS من تبويب CV أو ارفع نسختك"}

    sample = compose.compose_for_company(
        {"company_name": "شركة تجريبية", "city": "Jeddah", "sector": "Construction"},
        config,
    )
    subject = f"[TEST] {sample['subject']}"
    body_ar = sample["body_ar"] + "\n\n---\n[رسالة تجريبية من BetterJob]"
    body_en = sample["body_en"] + "\n\n---\n[Test message from BetterJob]"

    try:
        message_id = _dispatch_send(
            to_email, subject, body_ar, body_en, config, attachments
        )
        return {
            "success": True,
            "message_id": message_id,
            "to": to_email,
            "attachments": [
                {
                    "name": _attachment_filename(p, config),
                    "size_kb": p.stat().st_size // 1024,
                }
                for p in attachments
            ],
            "attachment": attachments[0].name,
            "size_kb": attachments[0].stat().st_size // 1024,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def send_production_preview(
    to_email: str,
    config: Optional[dict[str, Any]] = None,
    company_name: str = "شركة مقاولات / Construction Co.",
    city: str = "Jeddah",
    sector: str = "Construction",
) -> dict[str, Any]:
    """Send production-identical email (no TEST prefix) for HR inbox verification."""
    config = config or load_config()
    attachments = _resolve_attachments(config)
    if not attachments:
        return {"success": False, "error": "cv.pdf غير موجود — ولّد ATS من تبويب CV أو ارفع نسختك"}

    sample_company = {
        "company_name": company_name,
        "city": city,
        "sector": sector,
    }
    composed = compose.compose_for_company(sample_company, config)

    try:
        message_id = _dispatch_send(
            to_email,
            composed["subject"],
            composed["body_ar"],
            composed["body_en"],
            config,
            attachments,
        )
        return {
            "success": True,
            "message_id": message_id,
            "to": to_email,
            "subject": composed["subject"],
            "attachments": [
                {
                    "name": _attachment_filename(p, config),
                    "size_kb": p.stat().st_size // 1024,
                }
                for p in attachments
            ],
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def can_send_today(config: dict[str, Any]) -> tuple[bool, str]:
    max_per_day = config.get("sending", {}).get("max_per_day", 12)
    sent = db.count_sent_today()
    if sent >= max_per_day:
        return False, f"تم الوصول للحد اليومي ({max_per_day})"
    return True, f"متبقي {max_per_day - sent} رسالة اليوم"


def send_to_company(
    company_id: int,
    config: Optional[dict[str, Any]] = None,
    force_dry_run: Optional[bool] = None,
    skip_approval: bool = False,
) -> dict[str, Any]:
    config = config or load_config()
    sending_cfg = config.get("sending", {})
    auto_cfg = config.get("automation", {})
    dry_run = force_dry_run if force_dry_run is not None else sending_cfg.get("dry_run", True)
    require_approve = sending_cfg.get("require_manual_approve", True) and not skip_approval
    if auto_cfg.get("enabled") and auto_cfg.get("auto_send"):
        require_approve = False

    company = db.get_company(company_id)
    if not company:
        return {"success": False, "error": "الشركة غير موجودة"}

    allowed_statuses = ("approved", "sent", "email_found")
    if company["status"] not in allowed_statuses:
        return {"success": False, "error": f"حالة غير صالحة: {company['status']}"}

    if require_approve and company["status"] not in ("approved", "sent"):
        return {"success": False, "error": "الشركة لم تُوافق عليها بعد"}

    email_rec = db.get_primary_email(company_id)
    if not email_rec:
        return {"success": False, "error": "لا يوجد إيميل للشركة"}

    if email_rec["source"] == "guessed":
        return {"success": False, "error": "إيميل مُخمّن — لا يُرسل تلقائياً"}

    if not outreach_quality.is_auto_send_allowed(
        email_rec["email"], email_rec["source"], config,
        verified=bool(email_rec.get("verified")),
    ):
        tier = outreach_quality.classify_email(
            email_rec["email"], email_rec["source"],
            verified=bool(email_rec.get("verified")),
        )
        return {
            "success": False,
            "error": f"إيميل ضعيف ({tier}) — {email_rec['email']} — فضّل hr@ أو careers@",
        }

    if db.already_sent_to_email(company_id, email_rec["id"]):
        return {"success": False, "error": "تم الإرسال مسبقاً لهذا الإيميل"}

    ok, msg = can_send_today(config)
    if not ok and not dry_run:
        return {"success": False, "error": msg}

    composed = compose.compose_for_company(company, config)
    attachments = _resolve_attachments(config)
    if not attachments:
        return {"success": False, "error": "مرفق CV غير موجود — ولّد أو ارفع cv.pdf"}

    if dry_run:
        log_id = db.log_outreach(
            company_id=company_id,
            email_id=email_rec["id"],
            subject=composed["subject"],
            body_ar=composed["body_ar"],
            body_en=composed["body_en"],
            provider_message_id="DRY-RUN",
            cv_version="cv.pdf",
            dry_run=True,
            delivery_status=db.DELIVERY_SENT,
        )
        db.update_company_status(company_id, "sent")
        tracking.on_send_success(company_id, email_rec["id"], log_id, composed["subject"])
        return {
            "success": True,
            "dry_run": True,
            "log_id": log_id,
            "message": "تم التسجيل في وضع dry-run (لم يُرسل فعلياً)",
        }

    tracking.on_send_start(company_id, email_rec["id"], composed["subject"])

    try:
        message_id = _dispatch_send(
            email_rec["email"],
            composed["subject"],
            composed["body_ar"],
            composed["body_en"],
            config,
            attachments,
        )

        log_id = db.log_outreach(
            company_id=company_id,
            email_id=email_rec["id"],
            subject=composed["subject"],
            body_ar=composed["body_ar"],
            body_en=composed["body_en"],
            provider_message_id=message_id,
            cv_version="cv.pdf",
            dry_run=False,
            delivery_status=db.DELIVERY_SENT,
        )
        db.update_company_status(company_id, "sent")
        db.record_sent_company(
            company_id=company_id,
            outreach_log_id=log_id,
            company_name=company["company_name"],
            email=email_rec["email"],
            city=company.get("city"),
            sector=company.get("sector"),
            website=company.get("website"),
            discovery_source=company.get("discovery_source"),
            subject=composed["subject"],
            provider_message_id=message_id,
            delivery_status=db.DELIVERY_SENT,
            cv_attached=True,
        )
        tracking.on_send_success(company_id, email_rec["id"], log_id, composed["subject"])
        if config.get("application_strategy", {}).get("enabled"):
            try:
                import application_strategy

                application_strategy.record_successful_application(
                    company, log_id, composed["subject"], config
                )
            except Exception:
                pass

        delay = sending_cfg.get("delay_seconds_between", 45)
        time.sleep(delay)

        return {"success": True, "dry_run": False, "log_id": log_id, "message_id": message_id}

    except Exception as exc:
        err = str(exc)
        db.log_outreach(
            company_id=company_id,
            email_id=email_rec["id"],
            subject=composed["subject"],
            body_ar=composed["body_ar"],
            body_en=composed["body_en"],
            error_message=err,
            dry_run=False,
            delivery_status=db.DELIVERY_FAILED,
        )
        tracking.on_send_failure(company_id, email_rec["id"], err, composed["subject"])
        return {"success": False, "error": err}


def send_approved_batch(config: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    config = config or load_config()
    max_per_day = config.get("sending", {}).get("max_per_day", 12)
    remaining = max_per_day - db.count_sent_today()
    approved = db.get_approved_companies()[:remaining]

    results = []
    for company in approved:
        result = send_to_company(company["id"], config, skip_approval=True)
        results.append({"company": company["company_name"], **result})
        if not result.get("success"):
            break
    return results


def auto_send_all(
    config: Optional[dict[str, Any]] = None,
    on_progress: Optional[Any] = None,
) -> dict[str, Any]:
    """Auto-approve and send to all sendable companies up to daily limit."""
    config = config or load_config()
    auto = config.get("automation", {})
    cities = auto.get("target_cities")

    tracking.prepare_for_sending(cities)

    if auto.get("auto_approve", True):
        db.auto_approve_sendable(cities)

    max_per_day = config.get("sending", {}).get("max_per_day", 12)
    remaining = max_per_day - db.count_sent_today()
    raw_sendable = db.get_sendable_companies(cities)
    sendable, skipped_quality = outreach_quality.prioritize_sendable(raw_sendable, config)
    sendable = sendable[:remaining]

    results = []
    sent = 0
    failed = 0
    total = len(sendable)

    for i, company in enumerate(sendable, 1):
        if db.count_sent_today() >= max_per_day and not config.get("sending", {}).get("dry_run"):
            break
        if on_progress:
            on_progress(
                i, total,
                f"إرسال {i}/{total}: {company.get('company_name', '')[:40]} → {company.get('email', '')}",
            )
        result = send_to_company(company["id"], config, skip_approval=True)
        results.append({
            "company": company["company_name"],
            "city": company.get("city"),
            "email": company.get("email"),
            **result,
        })
        if result.get("success"):
            sent += 1
        else:
            failed += 1
            if "الحد اليومي" in result.get("error", ""):
                break

    return {
        "sent": sent,
        "failed": failed,
        "skipped_quality": len(skipped_quality),
        "remaining_today": max(0, max_per_day - db.count_sent_today()),
        "details": results,
    }


def test_connection(config: Optional[dict[str, Any]] = None) -> dict[str, str]:
    _load_env()
    config = config or load_config()
    provider = os.getenv("EMAIL_PROVIDER", "smtp").lower()

    if provider == "gmail":
        creds_path = BASE_DIR / "credentials.json"
        if not creds_path.exists():
            return {"status": "error", "message": "credentials.json غير موجود"}
        return {"status": "ok", "message": "Gmail credentials موجود — شغّل إرسال واحد لإكمال OAuth"}

    if provider == "brevo_api":
        key = os.getenv("BREVO_API_KEY", "")
        if not key or key.startswith("your_"):
            return {"status": "error", "message": "BREVO_API_KEY غير مضبوط في .env"}
        return {"status": "ok", "message": "Brevo API key موجود ✅"}

    if provider in ("brevo_smtp", "smtp"):
        host, port, login, pwd = _smtp_credentials()
        if not login or not pwd or pwd.startswith("your_"):
            return {"status": "error", "message": "SMTP_LOGIN / SMTP_PASSWORD غير مضبوطين"}
        if "brevo" in host and "@smtp-brevo.com" not in login:
            return {
                "status": "warn",
                "message": f"SMTP_LOGIN يجب أن يكون من Brevo (xxx@smtp-brevo.com) وليس {login}",
            }
        try:
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.starttls()
                server.login(login, pwd)
            label = "Brevo" if "brevo" in host else "SMTP"
            return {"status": "ok", "message": f"{label} متصل ✅ — login: {login}"}
        except Exception as exc:
            return {"status": "error", "message": f"فشل الاتصال: {exc}"}

    return {"status": "error", "message": f"مزود غير معروف: {provider}"}
