"""SQLite database layer for survey job outreach."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional

DB_PATH = Path(__file__).parent / "data" / "outreach.db"


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def get_connection(db_path: Path = DB_PATH) -> Generator[sqlite3.Connection, None, None]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT NOT NULL,
                city TEXT,
                region TEXT,
                sector TEXT,
                website TEXT,
                phone TEXT,
                google_place_id TEXT UNIQUE,
                place_types TEXT,
                status TEXT DEFAULT 'discovered',
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                email TEXT NOT NULL,
                source TEXT NOT NULL,
                is_primary INTEGER DEFAULT 0,
                verified INTEGER DEFAULT 0,
                UNIQUE(company_id, email),
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS outreach_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                email_id INTEGER,
                subject TEXT,
                body_ar TEXT,
                body_en TEXT,
                sent_at TEXT,
                provider_message_id TEXT,
                cv_version TEXT,
                error_message TEXT,
                dry_run INTEGER DEFAULT 0,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_companies_status ON companies(status);
            CREATE INDEX IF NOT EXISTS idx_companies_region ON companies(region);
            CREATE INDEX IF NOT EXISTS idx_outreach_sent_at ON outreach_log(sent_at);
            """
        )


def upsert_company(
    company_name: str,
    google_place_id: str,
    city: Optional[str] = None,
    region: Optional[str] = None,
    sector: Optional[str] = None,
    website: Optional[str] = None,
    phone: Optional[str] = None,
    place_types: Optional[list[str]] = None,
    status: str = "discovered",
    db_path: Path = DB_PATH,
) -> tuple[int, bool]:
    """Insert or update company. Returns (id, is_new)."""
    now = _utcnow()
    types_json = json.dumps(place_types or [], ensure_ascii=False)

    with get_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT id FROM companies WHERE google_place_id = ?",
            (google_place_id,),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE companies SET
                    company_name = ?, city = ?, region = ?, sector = ?,
                    website = COALESCE(?, website), phone = COALESCE(?, phone),
                    place_types = ?, updated_at = ?
                WHERE google_place_id = ?
                """,
                (
                    company_name,
                    city,
                    region,
                    sector,
                    website,
                    phone,
                    types_json,
                    now,
                    google_place_id,
                ),
            )
            return existing["id"], False

        cursor = conn.execute(
            """
            INSERT INTO companies (
                company_name, city, region, sector, website, phone,
                google_place_id, place_types, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                company_name,
                city,
                region,
                sector,
                website,
                phone,
                google_place_id,
                types_json,
                status,
                now,
                now,
            ),
        )
        return cursor.lastrowid, True


def add_email(
    company_id: int,
    email: str,
    source: str,
    is_primary: bool = False,
    verified: bool = False,
    db_path: Path = DB_PATH,
) -> Optional[int]:
    with get_connection(db_path) as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO emails (company_id, email, source, is_primary, verified)
                VALUES (?, ?, ?, ?, ?)
                """,
                (company_id, email.lower().strip(), source, int(is_primary), int(verified)),
            )
            if is_primary:
                conn.execute(
                    "UPDATE emails SET is_primary = 0 WHERE company_id = ? AND id != ?",
                    (company_id, cursor.lastrowid),
                )
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            return None


def update_company_status(company_id: int, status: str, db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE companies SET status = ?, updated_at = ? WHERE id = ?",
            (status, _utcnow(), company_id),
        )


def update_company_notes(company_id: int, notes: str, db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE companies SET notes = ?, updated_at = ? WHERE id = ?",
            (notes, _utcnow(), company_id),
        )


def get_companies(
    status: Optional[str] = None,
    region: Optional[str] = None,
    city: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    query = """
        SELECT c.*,
               (SELECT e.email FROM emails e
                WHERE e.company_id = c.id AND e.is_primary = 1
                LIMIT 1) AS primary_email,
               (SELECT e.source FROM emails e
                WHERE e.company_id = c.id AND e.is_primary = 1
                LIMIT 1) AS email_source
        FROM companies c WHERE 1=1
    """
    params: list[Any] = []
    if status:
        query += " AND c.status = ?"
        params.append(status)
    if region:
        query += " AND c.region = ?"
        params.append(region)
    if city:
        query += " AND c.city = ?"
        params.append(city)
    query += " ORDER BY c.updated_at DESC"

    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def get_company(company_id: int, db_path: Path = DB_PATH) -> Optional[dict[str, Any]]:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
        return dict(row) if row else None


def get_company_emails(company_id: int, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM emails WHERE company_id = ? ORDER BY is_primary DESC, id",
            (company_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_primary_email(company_id: int, db_path: Path = DB_PATH) -> Optional[dict[str, Any]]:
    emails = get_company_emails(company_id, db_path)
    for e in emails:
        if e["is_primary"]:
            return e
    return emails[0] if emails else None


def count_sent_today(db_path: Path = DB_PATH) -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM outreach_log
            WHERE sent_at LIKE ? AND dry_run = 0 AND error_message IS NULL
            """,
            (f"{today}%",),
        ).fetchone()
        return row["cnt"] if row else 0


def already_sent_to_email(company_id: int, email_id: int, db_path: Path = DB_PATH) -> bool:
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT 1 FROM outreach_log
            WHERE company_id = ? AND email_id = ? AND error_message IS NULL
            LIMIT 1
            """,
            (company_id, email_id),
        ).fetchone()
        return row is not None


def log_outreach(
    company_id: int,
    email_id: Optional[int],
    subject: str,
    body_ar: str,
    body_en: str,
    provider_message_id: Optional[str] = None,
    cv_version: str = "v1",
    error_message: Optional[str] = None,
    dry_run: bool = False,
    db_path: Path = DB_PATH,
) -> int:
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO outreach_log (
                company_id, email_id, subject, body_ar, body_en,
                sent_at, provider_message_id, cv_version, error_message, dry_run
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                company_id,
                email_id,
                subject,
                body_ar,
                body_en,
                _utcnow(),
                provider_message_id,
                cv_version,
                error_message,
                int(dry_run),
            ),
        )
        return cursor.lastrowid


def get_outreach_log(limit: int = 100, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT o.*, c.company_name, e.email
            FROM outreach_log o
            JOIN companies c ON c.id = o.company_id
            LEFT JOIN emails e ON e.id = o.email_id
            ORDER BY o.sent_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_stats(db_path: Path = DB_PATH) -> dict[str, int]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM companies GROUP BY status"
        ).fetchall()
        stats = {row["status"]: row["cnt"] for row in rows}
        stats["total"] = sum(stats.values())
        stats["sent_today"] = count_sent_today(db_path)
        return stats


def get_companies_without_email(db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT c.* FROM companies c
            WHERE c.website IS NOT NULL AND c.website != ''
            AND c.status IN ('discovered', 'no_email')
            AND NOT EXISTS (SELECT 1 FROM emails e WHERE e.company_id = c.id)
            ORDER BY c.id
            """
        ).fetchall()
        return [dict(row) for row in rows]


def get_approved_companies(db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT c.*, e.id AS email_id, e.email, e.source AS email_source
            FROM companies c
            JOIN emails e ON e.company_id = c.id AND e.is_primary = 1
            WHERE c.status = 'approved'
            AND e.source IN ('found_on_page', 'manual')
            ORDER BY c.id
            """
        ).fetchall()
        return [dict(row) for row in rows]


def get_sendable_companies(
    cities: Optional[list[str]] = None,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    """Companies with verified email, not yet sent."""
    query = """
        SELECT c.*, e.id AS email_id, e.email, e.source AS email_source
        FROM companies c
        JOIN emails e ON e.company_id = c.id AND e.is_primary = 1
        WHERE c.status IN ('email_found', 'approved')
        AND e.source IN ('found_on_page', 'manual')
        AND NOT EXISTS (
            SELECT 1 FROM outreach_log o
            WHERE o.company_id = c.id AND o.email_id = e.id AND o.error_message IS NULL
        )
    """
    params: list[Any] = []
    if cities:
        placeholders = ",".join("?" * len(cities))
        query += f" AND c.city IN ({placeholders})"
        params.extend(cities)

    query += " ORDER BY c.id"

    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def auto_approve_sendable(cities: Optional[list[str]] = None, db_path: Path = DB_PATH) -> int:
    companies = get_sendable_companies(cities, db_path)
    count = 0
    for company in companies:
        if company["status"] == "email_found":
            update_company_status(company["id"], "approved", db_path)
            count += 1
    return count
