"""Persistence for BetterJob Pro application strategy and follow-ups."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from database import DB_PATH, get_connection, _utcnow


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _parse_dt(value: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(timezone.utc)


def record_application(
    company_id: int,
    outreach_log_id: Optional[int],
    job_title_en: str,
    job_title_ar: str,
    tier: str,
    hook_key: str,
    subject: str,
    next_follow_up_at: Optional[str] = None,
    db_path=DB_PATH,
) -> int:
    now = _utcnow()
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO strategy_applications (
                company_id, outreach_log_id, job_title_en, job_title_ar,
                tier, hook_key, subject, applied_at, follow_up_stage,
                next_follow_up_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 'sent')
            """,
            (
                company_id,
                outreach_log_id,
                job_title_en,
                job_title_ar,
                tier,
                hook_key,
                subject,
                now,
                next_follow_up_at,
            ),
        )
        return int(cur.lastrowid)


def schedule_follow_ups(
    application_id: int,
    company_id: int,
    applied_at: str,
    stages: list[dict[str, Any]],
    db_path=DB_PATH,
) -> int:
    base = _parse_dt(applied_at)
    count = 0
    with get_connection(db_path) as conn:
        for stage in stages:
            due = base + timedelta(days=int(stage.get("days_after", 3)))
            conn.execute(
                """
                INSERT INTO strategy_follow_ups (
                    application_id, company_id, stage, channel, due_at, status
                ) VALUES (?, ?, ?, ?, ?, 'pending')
                """,
                (
                    application_id,
                    company_id,
                    int(stage.get("stage", 1)),
                    stage.get("channel", "email"),
                    due.strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            count += 1
        first = stages[0] if stages else None
        if first:
            due0 = base + timedelta(days=int(first.get("days_after", 3)))
            conn.execute(
                """
                UPDATE strategy_applications
                SET next_follow_up_at = ?
                WHERE id = ?
                """,
                (due0.strftime("%Y-%m-%d %H:%M:%S"), application_id),
            )
    return count


def count_applications_on_date(date_str: Optional[str] = None, db_path=DB_PATH) -> int:
    day = date_str or _today()
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM strategy_applications
            WHERE applied_at LIKE ?
            """,
            (f"{day}%",),
        ).fetchone()
        return int(row["n"]) if row else 0


def count_applications_in_range(start: str, end: str, db_path=DB_PATH) -> int:
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM strategy_applications
            WHERE date(applied_at) >= date(?) AND date(applied_at) <= date(?)
            """,
            (start, end),
        ).fetchone()
        return int(row["n"]) if row else 0


def count_by_tier_on_date(tier: str, date_str: Optional[str] = None, db_path=DB_PATH) -> int:
    day = date_str or _today()
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM strategy_applications
            WHERE tier = ? AND applied_at LIKE ?
            """,
            (tier, f"{day}%"),
        ).fetchone()
        return int(row["n"]) if row else 0


def count_by_tier_in_week(tier: str, db_path=DB_PATH) -> int:
    start = (datetime.now(timezone.utc) - timedelta(days=datetime.now(timezone.utc).weekday())).strftime("%Y-%m-%d")
    end = _today()
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM strategy_applications
            WHERE tier = ? AND date(applied_at) >= date(?) AND date(applied_at) <= date(?)
            """,
            (tier, start, end),
        ).fetchone()
        return int(row["n"]) if row else 0


def get_application_for_company(company_id: int, db_path=DB_PATH) -> Optional[dict[str, Any]]:
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT * FROM strategy_applications
            WHERE company_id = ?
            ORDER BY applied_at DESC LIMIT 1
            """,
            (company_id,),
        ).fetchone()
        return dict(row) if row else None


def get_due_follow_ups(limit: int = 50, db_path=DB_PATH) -> list[dict[str, Any]]:
    now = _utcnow()
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT f.*, a.job_title_en, a.job_title_ar, a.subject AS original_subject,
                   a.applied_at, c.company_name, c.city, c.phone, c.website,
                   e.email AS primary_email
            FROM strategy_follow_ups f
            JOIN strategy_applications a ON a.id = f.application_id
            JOIN companies c ON c.id = f.company_id
            LEFT JOIN emails e ON e.company_id = c.id AND e.is_primary = 1
            WHERE f.status = 'pending' AND f.due_at <= ?
            ORDER BY f.due_at ASC
            LIMIT ?
            """,
            (now, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def complete_follow_up(follow_up_id: int, db_path=DB_PATH) -> None:
    now = _utcnow()
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT application_id, stage FROM strategy_follow_ups WHERE id = ?",
            (follow_up_id,),
        ).fetchone()
        if not row:
            return
        conn.execute(
            """
            UPDATE strategy_follow_ups
            SET status = 'completed', completed_at = ?
            WHERE id = ?
            """,
            (now, follow_up_id),
        )
        next_fu = conn.execute(
            """
            SELECT due_at FROM strategy_follow_ups
            WHERE application_id = ? AND status = 'pending'
            ORDER BY stage ASC LIMIT 1
            """,
            (row["application_id"],),
        ).fetchone()
        conn.execute(
            """
            UPDATE strategy_applications
            SET follow_up_stage = ?, last_follow_up_at = ?,
                next_follow_up_at = ?
            WHERE id = ?
            """,
            (
                row["stage"],
                now,
                next_fu["due_at"] if next_fu else None,
                row["application_id"],
            ),
        )


def update_application_status(
    company_id: int,
    status: str,
    notes: Optional[str] = None,
    db_path=DB_PATH,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE strategy_applications
            SET status = ?, notes = COALESCE(?, notes)
            WHERE company_id = ?
            """,
            (status, notes, company_id),
        )


def get_strategy_stats(db_path=DB_PATH) -> dict[str, Any]:
    today = _today()
    week_start = (
        datetime.now(timezone.utc) - timedelta(days=datetime.now(timezone.utc).weekday())
    ).strftime("%Y-%m-%d")
    with get_connection(db_path) as conn:
        total_apps = conn.execute("SELECT COUNT(*) AS n FROM strategy_applications").fetchone()["n"]
        today_apps = conn.execute(
            "SELECT COUNT(*) AS n FROM strategy_applications WHERE applied_at LIKE ?",
            (f"{today}%",),
        ).fetchone()["n"]
        week_apps = conn.execute(
            """
            SELECT COUNT(*) AS n FROM strategy_applications
            WHERE date(applied_at) >= date(?)
            """,
            (week_start,),
        ).fetchone()["n"]
        pending_fu = conn.execute(
            "SELECT COUNT(*) AS n FROM strategy_follow_ups WHERE status = 'pending'"
        ).fetchone()["n"]
        due_fu = conn.execute(
            """
            SELECT COUNT(*) AS n FROM strategy_follow_ups
            WHERE status = 'pending' AND due_at <= ?
            """,
            (_utcnow(),),
        ).fetchone()["n"]
        replied = conn.execute(
            "SELECT COUNT(*) AS n FROM strategy_applications WHERE status = 'replied'"
        ).fetchone()["n"]
        interview = conn.execute(
            "SELECT COUNT(*) AS n FROM strategy_applications WHERE status = 'interview'"
        ).fetchone()["n"]
    return {
        "total_applications": total_apps,
        "today_applications": today_apps,
        "week_applications": week_apps,
        "pending_follow_ups": pending_fu,
        "due_follow_ups": due_fu,
        "replied": replied,
        "interview": interview,
    }


def list_recent_applications(limit: int = 30, db_path=DB_PATH) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT a.*, c.company_name, c.city, c.job_fit_score
            FROM strategy_applications a
            JOIN companies c ON c.id = a.company_id
            ORDER BY a.applied_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
