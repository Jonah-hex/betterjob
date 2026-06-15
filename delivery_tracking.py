"""CV / email delivery pipeline — track sent, pending, delivered, failed, not sent."""

from __future__ import annotations

from typing import Any, Optional

import database as db

_STATUS_LABELS_AR = {
    "delivered": "✅ مُستلم",
    "sent": "📤 مُرسل",
    "pending": "⏳ معلق",
    "queued": "⏳ في الطابور",
    "sending": "🔄 جاري الإرسال",
    "failed": "❌ فشل",
    "bounced": "↩️ مرتد",
    "not_sent": "📭 لم يُرسل",
    "no_email": "🚫 بدون إيميل",
}


def label(status: str) -> str:
    return _STATUS_LABELS_AR.get(status, status)


def sync_pipeline(cities: Optional[list[str]] = None) -> int:
    """Sync sendable companies into the pending queue."""
    return db.sync_sendable_to_queue(cities)


def get_pipeline_summary(cities: Optional[list[str]] = None) -> dict[str, Any]:
    pending = db.get_queue_by_status(db.DELIVERY_PENDING, cities)
    queued = db.get_queue_by_status(db.DELIVERY_QUEUED, cities)
    sending = db.get_queue_by_status(db.DELIVERY_SENDING, cities)
    delivered = db.get_sent_by_delivery_status(db.DELIVERY_DELIVERED)
    sent_awaiting = db.get_sent_by_delivery_status(db.DELIVERY_SENT)
    failed = db.get_failed_deliveries(cities)
    not_sent_ready = db.get_sendable_companies(cities)
    no_email = db.get_no_email_companies(cities)

    if cities:
        delivered = [r for r in delivered if r.get("city") in cities]
        sent_awaiting = [r for r in sent_awaiting if r.get("city") in cities]

    pending_all = pending + queued + sending
    return {
        "delivered": len(delivered),
        "sent": len(sent_awaiting),
        "pending": len(pending_all),
        "not_sent": len(not_sent_ready),
        "failed": len(failed),
        "no_email": len(no_email),
        "delivered_list": delivered,
        "sent_list": sent_awaiting,
        "pending_list": pending_all,
        "not_sent_list": not_sent_ready,
        "failed_list": failed,
        "no_email_list": no_email,
    }


def prepare_for_sending(cities: Optional[list[str]] = None) -> dict[str, int]:
    """Queue all sendable companies before a send batch."""
    synced = sync_pipeline(cities)
    approved = db.auto_approve_sendable(cities)
    for company in db.get_sendable_companies(cities):
        email_id = company.get("email_id")
        if email_id:
            db.update_queue_status(
                company["id"], email_id, db.DELIVERY_QUEUED
            )
    return {"queued": synced, "approved": approved}


def on_send_start(company_id: int, email_id: int, subject: str) -> None:
    db.upsert_queue_item(
        company_id, email_id, status=db.DELIVERY_SENDING, subject=subject
    )


def on_send_success(
    company_id: int,
    email_id: int,
    outreach_log_id: int,
    subject: str,
) -> None:
    db.update_queue_status(
        company_id,
        email_id,
        db.DELIVERY_SENT,
        outreach_log_id=outreach_log_id,
    )


def on_send_failure(
    company_id: int,
    email_id: int,
    error: str,
    subject: str = "",
) -> None:
    db.upsert_queue_item(
        company_id,
        email_id,
        status=db.DELIVERY_FAILED,
        subject=subject,
        last_error=error,
        increment_attempts=True,
    )


def mark_company_delivered(company_id: int, outreach_log_id: Optional[int] = None) -> None:
    db.mark_delivered(company_id, outreach_log_id)


def retry_failed(company_id: int, cities: Optional[list[str]] = None) -> bool:
    """Re-queue a failed company if it has email and was not successfully sent."""
    company = db.get_company(company_id)
    email_rec = db.get_primary_email(company_id)
    if not company or not email_rec:
        return False
    if db.already_sent_to_email(company_id, email_rec["id"]):
        return False
    db.update_company_status(company_id, "approved")
    db.update_queue_status(company_id, email_rec["id"], db.DELIVERY_PENDING)
    return True
