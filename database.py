"""SQLite database layer for survey job outreach."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional

DB_PATH = Path(__file__).parent / "data" / "outreach.db"

SENDABLE_EMAIL_SOURCES = (
    "found_on_page",
    "manual",
    "csv",
    "google_places",
)

# حالات تسليم CV / الإيميل
DELIVERY_NOT_SENT = "not_sent"
DELIVERY_PENDING = "pending"
DELIVERY_QUEUED = "queued"
DELIVERY_SENDING = "sending"
DELIVERY_SENT = "sent"
DELIVERY_DELIVERED = "delivered"
DELIVERY_FAILED = "failed"
DELIVERY_BOUNCED = "bounced"
DELIVERY_NO_EMAIL = "no_email"


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

            CREATE TABLE IF NOT EXISTS sent_companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL UNIQUE,
                outreach_log_id INTEGER,
                company_name TEXT NOT NULL,
                email TEXT NOT NULL,
                city TEXT,
                sector TEXT,
                website TEXT,
                discovery_source TEXT,
                subject TEXT,
                sent_at TEXT NOT NULL,
                provider_message_id TEXT,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                FOREIGN KEY (outreach_log_id) REFERENCES outreach_log(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sent_companies_sent_at ON sent_companies(sent_at);

            CREATE TABLE IF NOT EXISTS email_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                email_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                subject TEXT,
                outreach_log_id INTEGER,
                attempts INTEGER DEFAULT 0,
                last_error TEXT,
                cv_attached INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(company_id, email_id),
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE CASCADE,
                FOREIGN KEY (outreach_log_id) REFERENCES outreach_log(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_email_queue_status ON email_queue(status);
            """
        )
        _migrate_schema(conn)
        _backfill_sent_companies(conn)
        _sync_delivery_from_history(conn)


def _migrate_schema(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(companies)").fetchall()}
    if "discovery_source" not in cols:
        conn.execute("ALTER TABLE companies ADD COLUMN discovery_source TEXT DEFAULT 'unknown'")

    outreach_cols = {row[1] for row in conn.execute("PRAGMA table_info(outreach_log)").fetchall()}
    if "delivery_status" not in outreach_cols:
        conn.execute(
            "ALTER TABLE outreach_log ADD COLUMN delivery_status TEXT DEFAULT 'sent'"
        )
    if "delivered_at" not in outreach_cols:
        conn.execute("ALTER TABLE outreach_log ADD COLUMN delivered_at TEXT")
    if "bounce_reason" not in outreach_cols:
        conn.execute("ALTER TABLE outreach_log ADD COLUMN bounce_reason TEXT")

    sent_cols = {row[1] for row in conn.execute("PRAGMA table_info(sent_companies)").fetchall()}
    if "delivery_status" not in sent_cols:
        conn.execute(
            "ALTER TABLE sent_companies ADD COLUMN delivery_status TEXT DEFAULT 'sent'"
        )
    if "delivered_at" not in sent_cols:
        conn.execute("ALTER TABLE sent_companies ADD COLUMN delivered_at TEXT")
    if "cv_attached" not in sent_cols:
        conn.execute("ALTER TABLE sent_companies ADD COLUMN cv_attached INTEGER DEFAULT 1")

    company_cols = {row[1] for row in conn.execute("PRAGMA table_info(companies)").fetchall()}
    for col, ddl in (
        ("linkedin_url", "ALTER TABLE companies ADD COLUMN linkedin_url TEXT"),
        ("careers_url", "ALTER TABLE companies ADD COLUMN careers_url TEXT"),
        ("job_url", "ALTER TABLE companies ADD COLUMN job_url TEXT"),
        ("job_fit_score", "ALTER TABLE companies ADD COLUMN job_fit_score INTEGER DEFAULT 0"),
    ):
        if col not in company_cols:
            conn.execute(ddl)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS whatsapp_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            phone TEXT NOT NULL,
            message TEXT,
            status TEXT DEFAULT 'opened',
            created_at TEXT NOT NULL,
            FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            outreach_log_id INTEGER,
            job_title_en TEXT NOT NULL,
            job_title_ar TEXT,
            tier TEXT NOT NULL,
            hook_key TEXT,
            subject TEXT,
            applied_at TEXT NOT NULL,
            follow_up_stage INTEGER DEFAULT 0,
            next_follow_up_at TEXT,
            last_follow_up_at TEXT,
            status TEXT DEFAULT 'sent',
            notes TEXT,
            FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
            FOREIGN KEY (outreach_log_id) REFERENCES outreach_log(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_strategy_apps_company ON strategy_applications(company_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_strategy_apps_follow_up ON strategy_applications(next_follow_up_at)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_follow_ups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER NOT NULL,
            company_id INTEGER NOT NULL,
            stage INTEGER NOT NULL,
            channel TEXT NOT NULL,
            due_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT DEFAULT 'pending',
            subject TEXT,
            body_ar TEXT,
            body_en TEXT,
            FOREIGN KEY (application_id) REFERENCES strategy_applications(id) ON DELETE CASCADE,
            FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_strategy_fu_due ON strategy_follow_ups(due_at, status)"
    )


def _sync_delivery_from_history(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE outreach_log SET delivery_status = 'sent'
        WHERE dry_run = 0 AND error_message IS NULL
        AND (delivery_status IS NULL OR delivery_status = '')
        """
    )
    conn.execute(
        """
        UPDATE outreach_log SET delivery_status = 'failed'
        WHERE error_message IS NOT NULL AND dry_run = 0
        AND (delivery_status IS NULL OR delivery_status = '')
        """
    )
    conn.execute(
        """
        UPDATE sent_companies SET delivery_status = 'sent'
        WHERE delivery_status IS NULL OR delivery_status = ''
        """
    )


def _backfill_sent_companies(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT o.id AS outreach_log_id, o.company_id, o.subject, o.sent_at, o.provider_message_id,
               c.company_name, c.city, c.sector, c.website, c.discovery_source, e.email
        FROM outreach_log o
        JOIN companies c ON c.id = o.company_id
        LEFT JOIN emails e ON e.id = o.email_id
        WHERE o.dry_run = 0 AND o.error_message IS NULL
        ORDER BY o.sent_at DESC
        """
    ).fetchall()
    for row in rows:
        conn.execute(
            """
            INSERT OR IGNORE INTO sent_companies (
                company_id, outreach_log_id, company_name, email, city, sector,
                website, discovery_source, subject, sent_at, provider_message_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["company_id"],
                row["outreach_log_id"],
                row["company_name"],
                row["email"] or "",
                row["city"],
                row["sector"],
                row["website"],
                row["discovery_source"],
                row["subject"],
                row["sent_at"],
                row["provider_message_id"],
            ),
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
    discovery_source: Optional[str] = None,
    linkedin_url: Optional[str] = None,
    careers_url: Optional[str] = None,
    job_url: Optional[str] = None,
    job_fit_score: Optional[int] = None,
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
                    place_types = ?, discovery_source = COALESCE(?, discovery_source),
                    linkedin_url = COALESCE(?, linkedin_url),
                    careers_url = COALESCE(?, careers_url),
                    job_url = COALESCE(?, job_url),
                    job_fit_score = COALESCE(?, job_fit_score),
                    updated_at = ?
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
                    discovery_source,
                    linkedin_url,
                    careers_url,
                    job_url,
                    job_fit_score,
                    now,
                    google_place_id,
                ),
            )
            return existing["id"], False

        cursor = conn.execute(
            """
            INSERT INTO companies (
                company_name, city, region, sector, website, phone,
                google_place_id, place_types, status, discovery_source,
                linkedin_url, careers_url, job_url, job_fit_score,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                discovery_source or "unknown",
                linkedin_url,
                careers_url,
                job_url,
                job_fit_score or 0,
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
            WHERE company_id = ? AND email_id = ? AND error_message IS NULL AND dry_run = 0
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
    delivery_status: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> int:
    if delivery_status is None:
        if dry_run:
            delivery_status = DELIVERY_SENT
        elif error_message:
            delivery_status = DELIVERY_FAILED
        else:
            delivery_status = DELIVERY_SENT

    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO outreach_log (
                company_id, email_id, subject, body_ar, body_en,
                sent_at, provider_message_id, cv_version, error_message, dry_run,
                delivery_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                delivery_status,
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
        sent_row = conn.execute("SELECT COUNT(*) AS cnt FROM sent_companies").fetchone()
        stats["sent_confirmed"] = sent_row["cnt"] if sent_row else 0
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
    placeholders = ",".join("?" * len(SENDABLE_EMAIL_SOURCES))
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT c.*, e.id AS email_id, e.email, e.source AS email_source
            FROM companies c
            JOIN emails e ON e.company_id = c.id AND e.is_primary = 1
            WHERE c.status = 'approved'
            AND e.source IN ({placeholders})
            ORDER BY c.id
            """,
            list(SENDABLE_EMAIL_SOURCES),
        ).fetchall()
        return [dict(row) for row in rows]


def get_sendable_companies(
    cities: Optional[list[str]] = None,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    """Companies with verified email, not yet sent."""
    src_placeholders = ",".join("?" * len(SENDABLE_EMAIL_SOURCES))
    query = f"""
        SELECT c.*, e.id AS email_id, e.email, e.source AS email_source,
               e.verified AS email_verified
        FROM companies c
        JOIN emails e ON e.company_id = c.id AND e.is_primary = 1
        WHERE c.status IN ('email_found', 'approved')
        AND e.source IN ({src_placeholders})
        AND NOT EXISTS (
            SELECT 1 FROM outreach_log o
            WHERE o.company_id = c.id AND o.email_id = e.id
            AND o.error_message IS NULL AND o.dry_run = 0
        )
    """
    params: list[Any] = list(SENDABLE_EMAIL_SOURCES)
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


def record_sent_company(
    company_id: int,
    outreach_log_id: int,
    company_name: str,
    email: str,
    city: Optional[str] = None,
    sector: Optional[str] = None,
    website: Optional[str] = None,
    discovery_source: Optional[str] = None,
    subject: Optional[str] = None,
    provider_message_id: Optional[str] = None,
    sent_at: Optional[str] = None,
    delivery_status: str = DELIVERY_SENT,
    cv_attached: bool = True,
    db_path: Path = DB_PATH,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO sent_companies (
                company_id, outreach_log_id, company_name, email, city, sector,
                website, discovery_source, subject, sent_at, provider_message_id,
                delivery_status, cv_attached
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(company_id) DO UPDATE SET
                outreach_log_id = excluded.outreach_log_id,
                company_name = excluded.company_name,
                email = excluded.email,
                city = excluded.city,
                sector = excluded.sector,
                website = excluded.website,
                discovery_source = excluded.discovery_source,
                subject = excluded.subject,
                sent_at = excluded.sent_at,
                provider_message_id = excluded.provider_message_id,
                delivery_status = excluded.delivery_status,
                cv_attached = excluded.cv_attached
            """,
            (
                company_id,
                outreach_log_id,
                company_name,
                email,
                city,
                sector,
                website,
                discovery_source,
                subject,
                sent_at or _utcnow(),
                provider_message_id,
                delivery_status,
                int(cv_attached),
            ),
        )


def get_sent_companies(
    city: Optional[str] = None,
    limit: int = 500,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM sent_companies WHERE 1=1"
    params: list[Any] = []
    if city:
        query += " AND city = ?"
        params.append(city)
    query += " ORDER BY sent_at DESC LIMIT ?"
    params.append(limit)
    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def get_discovery_stats(db_path: Path = DB_PATH) -> dict[str, int]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT COALESCE(discovery_source, 'unknown') AS src, COUNT(*) AS cnt
            FROM companies GROUP BY src
            """
        ).fetchall()
        return {row["src"]: row["cnt"] for row in rows}


def upsert_queue_item(
    company_id: int,
    email_id: int,
    status: str = DELIVERY_PENDING,
    subject: Optional[str] = None,
    outreach_log_id: Optional[int] = None,
    last_error: Optional[str] = None,
    increment_attempts: bool = False,
    db_path: Path = DB_PATH,
) -> int:
    now = _utcnow()
    with get_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT id, attempts FROM email_queue WHERE company_id = ? AND email_id = ?",
            (company_id, email_id),
        ).fetchone()
        attempts = (existing["attempts"] if existing else 0) + (1 if increment_attempts else 0)
        if existing:
            conn.execute(
                """
                UPDATE email_queue SET
                    status = ?, subject = COALESCE(?, subject),
                    outreach_log_id = COALESCE(?, outreach_log_id),
                    attempts = ?, last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, subject, outreach_log_id, attempts, last_error, now, existing["id"]),
            )
            return existing["id"]
        cursor = conn.execute(
            """
            INSERT INTO email_queue (
                company_id, email_id, status, subject, outreach_log_id,
                attempts, last_error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (company_id, email_id, status, subject, outreach_log_id, attempts, last_error, now, now),
        )
        return cursor.lastrowid


def update_queue_status(
    company_id: int,
    email_id: int,
    status: str,
    outreach_log_id: Optional[int] = None,
    last_error: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> None:
    upsert_queue_item(
        company_id,
        email_id,
        status=status,
        outreach_log_id=outreach_log_id,
        last_error=last_error,
        increment_attempts=(status == DELIVERY_FAILED),
        db_path=db_path,
    )


def mark_delivered(
    company_id: int,
    outreach_log_id: Optional[int] = None,
    db_path: Path = DB_PATH,
) -> None:
    now = _utcnow()
    with get_connection(db_path) as conn:
        if outreach_log_id:
            conn.execute(
                """
                UPDATE outreach_log SET delivery_status = ?, delivered_at = ?
                WHERE id = ?
                """,
                (DELIVERY_DELIVERED, now, outreach_log_id),
            )
        conn.execute(
            """
            UPDATE sent_companies SET delivery_status = ?, delivered_at = ?
            WHERE company_id = ?
            """,
            (DELIVERY_DELIVERED, now, company_id),
        )
    email_row = get_primary_email(company_id, db_path)
    if email_row:
        update_queue_status(
            company_id, email_row["id"], DELIVERY_DELIVERED, outreach_log_id, db_path=db_path
        )


def sync_sendable_to_queue(
    cities: Optional[list[str]] = None,
    db_path: Path = DB_PATH,
) -> int:
    """Add sendable companies to queue as pending."""
    count = 0
    for company in get_sendable_companies(cities, db_path):
        email_id = company.get("email_id")
        if not email_id:
            continue
        upsert_queue_item(
            company["id"],
            email_id,
            status=DELIVERY_PENDING,
            db_path=db_path,
        )
        count += 1
    return count


def get_queue_by_status(
    status: str,
    cities: Optional[list[str]] = None,
    limit: int = 500,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    query = """
        SELECT q.*, c.company_name, c.city, c.sector, c.website, c.discovery_source, e.email
        FROM email_queue q
        JOIN companies c ON c.id = q.company_id
        JOIN emails e ON e.id = q.email_id
        WHERE q.status = ?
    """
    params: list[Any] = [status]
    if cities:
        placeholders = ",".join("?" * len(cities))
        query += f" AND c.city IN ({placeholders})"
        params.extend(cities)
    query += " ORDER BY q.updated_at DESC LIMIT ?"
    params.append(limit)
    with get_connection(db_path) as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def get_sent_by_delivery_status(
    delivery_status: str,
    city: Optional[str] = None,
    limit: int = 500,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM sent_companies WHERE delivery_status = ?"
    params: list[Any] = [delivery_status]
    if city:
        query += " AND city = ?"
        params.append(city)
    query += " ORDER BY sent_at DESC LIMIT ?"
    params.append(limit)
    with get_connection(db_path) as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def get_failed_deliveries(
    cities: Optional[list[str]] = None,
    limit: int = 200,
    unresolved_only: bool = True,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    """Failed sends. By default only unresolved: latest real attempt still failed."""
    if unresolved_only:
        query = """
            WITH latest AS (
                SELECT company_id, email_id, MAX(sent_at) AS last_sent
                FROM outreach_log
                WHERE dry_run = 0
                GROUP BY company_id, email_id
            )
            SELECT o.*, c.company_name, c.city, e.email
            FROM outreach_log o
            JOIN latest l
                ON o.company_id = l.company_id
                AND o.email_id = l.email_id
                AND o.sent_at = l.last_sent
            JOIN companies c ON c.id = o.company_id
            LEFT JOIN emails e ON e.id = o.email_id
            WHERE o.dry_run = 0 AND o.error_message IS NOT NULL
        """
    else:
        query = """
            SELECT o.*, c.company_name, c.city, e.email
            FROM outreach_log o
            JOIN companies c ON c.id = o.company_id
            LEFT JOIN emails e ON e.id = o.email_id
            WHERE o.dry_run = 0 AND o.error_message IS NOT NULL
        """
    params: list[Any] = []
    if cities:
        placeholders = ",".join("?" * len(cities))
        query += f" AND c.city IN ({placeholders})"
        params.extend(cities)
    query += " ORDER BY o.sent_at DESC LIMIT ?"
    params.append(limit)
    with get_connection(db_path) as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def get_not_sent_companies(
    cities: Optional[list[str]] = None,
    limit: int = 500,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    """Companies with email, never successfully sent."""
    src_placeholders = ",".join("?" * len(SENDABLE_EMAIL_SOURCES))
    query = f"""
        SELECT c.*, e.id AS email_id, e.email, e.source AS email_source
        FROM companies c
        JOIN emails e ON e.company_id = c.id AND e.is_primary = 1
        WHERE e.source IN ({src_placeholders})
        AND NOT EXISTS (
            SELECT 1 FROM outreach_log o
            WHERE o.company_id = c.id AND o.email_id = e.id
            AND o.error_message IS NULL AND o.dry_run = 0
        )
        AND NOT EXISTS (
            SELECT 1 FROM email_queue q
            WHERE q.company_id = c.id AND q.email_id = e.id
            AND q.status IN ('pending', 'queued', 'sending')
        )
    """
    params: list[Any] = list(SENDABLE_EMAIL_SOURCES)
    if cities:
        placeholders = ",".join("?" * len(cities))
        query += f" AND c.city IN ({placeholders})"
        params.extend(cities)
    query += " ORDER BY c.id LIMIT ?"
    params.append(limit)
    with get_connection(db_path) as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def get_no_email_companies(
    cities: Optional[list[str]] = None,
    limit: int = 500,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    query = """
        SELECT c.* FROM companies c
        WHERE NOT EXISTS (SELECT 1 FROM emails e WHERE e.company_id = c.id)
        OR c.status = 'no_email'
    """
    params: list[Any] = []
    if cities:
        placeholders = ",".join("?" * len(cities))
        query += f" AND c.city IN ({placeholders})"
        params.extend(cities)
    query += " ORDER BY c.updated_at DESC LIMIT ?"
    params.append(limit)
    with get_connection(db_path) as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def update_company_job_fit(company_id: int, score: int, db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE companies SET job_fit_score = ?, updated_at = ? WHERE id = ?",
            (score, _utcnow(), company_id),
        )


def log_whatsapp(
    company_id: int,
    phone: str,
    message: str,
    status: str = "opened",
    db_path: Path = DB_PATH,
) -> int:
    now = _utcnow()
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO whatsapp_log (company_id, phone, message, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (company_id, phone, message, status, now),
        )
        return cur.lastrowid or 0


def get_whatsapp_log(limit: int = 100, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT w.*, c.company_name
            FROM whatsapp_log w
            JOIN companies c ON c.id = w.company_id
            ORDER BY w.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

