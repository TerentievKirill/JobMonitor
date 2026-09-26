import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    channel_title TEXT NOT NULL,
    channel_username TEXT,
    published_at TEXT,
    edited_at TEXT,
    collected_at TEXT NOT NULL,
    text TEXT NOT NULL,
    links_json TEXT NOT NULL,
    telegram_url TEXT,
    has_media INTEGER NOT NULL DEFAULT 0,
    is_forwarded INTEGER NOT NULL DEFAULT 0,
    views INTEGER,
    forwards INTEGER,
    raw_json TEXT,
    fingerprint TEXT NOT NULL,
    classification TEXT NOT NULL,
    filter_reason TEXT,
    duplicate_of_id INTEGER REFERENCES messages(id),
    UNIQUE(channel_id, message_id)
);

CREATE INDEX IF NOT EXISTS ix_messages_fingerprint
    ON messages(fingerprint);
CREATE INDEX IF NOT EXISTS ix_messages_published_at
    ON messages(published_at);
CREATE INDEX IF NOT EXISTS ix_messages_classification
    ON messages(classification);

CREATE TABLE IF NOT EXISTS collection_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    sources_count INTEGER NOT NULL DEFAULT 0,
    received_count INTEGER NOT NULL DEFAULT 0,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    vacancies_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    duplicates_count INTEGER NOT NULL DEFAULT 0,
    errors_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);

DROP VIEW IF EXISTS vacancies;
CREATE VIEW vacancies AS
SELECT
    id,
    channel_id,
    message_id,
    channel_title,
    channel_username,
    published_at,
    collected_at,
    text,
    links_json,
    telegram_url,
    has_media,
    views,
    fingerprint
FROM messages
WHERE classification = 'vacancy'
  AND duplicate_of_id IS NULL;

PRAGMA user_version = 1;
"""


@dataclass
class InsertResult:
    inserted: bool
    classification: str | None = None
    duplicate: bool = False


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA)

    def last_message_id(self, channel_id: int) -> int | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT MAX(message_id) AS value FROM messages WHERE channel_id = ?",
                (channel_id,),
            ).fetchone()
        return row["value"] if row and row["value"] is not None else None

    def insert_message(self, record: dict[str, Any]) -> InsertResult:
        with self.connect() as connection:
            exists = connection.execute(
                "SELECT id FROM messages WHERE channel_id = ? AND message_id = ?",
                (record["channel_id"], record["message_id"]),
            ).fetchone()
            if exists:
                return InsertResult(inserted=False)

            duplicate_of_id = None
            if record["classification"] == "vacancy":
                duplicate = connection.execute(
                    """
                    SELECT id
                    FROM messages
                    WHERE fingerprint = ?
                      AND classification = 'vacancy'
                      AND duplicate_of_id IS NULL
                    ORDER BY id
                    LIMIT 1
                    """,
                    (record["fingerprint"],),
                ).fetchone()
                if duplicate:
                    duplicate_of_id = duplicate["id"]

            connection.execute(
                """
                INSERT INTO messages (
                    channel_id, message_id, channel_title, channel_username,
                    published_at, edited_at, collected_at, text, links_json,
                    telegram_url, has_media, is_forwarded, views, forwards,
                    raw_json, fingerprint, classification, filter_reason,
                    duplicate_of_id
                ) VALUES (
                    :channel_id, :message_id, :channel_title, :channel_username,
                    :published_at, :edited_at, :collected_at, :text, :links_json,
                    :telegram_url, :has_media, :is_forwarded, :views, :forwards,
                    :raw_json, :fingerprint, :classification, :filter_reason,
                    :duplicate_of_id
                )
                """,
                {**record, "duplicate_of_id": duplicate_of_id},
            )
            return InsertResult(
                inserted=True,
                classification=record["classification"],
                duplicate=duplicate_of_id is not None,
            )

    def start_run(self) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO collection_runs (started_at, status) VALUES (?, 'running')",
                (datetime.now(timezone.utc).isoformat(),),
            )
            return int(cursor.lastrowid)

    def finish_run(self, run_id: int, stats: dict[str, int], error: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE collection_runs
                SET finished_at = ?, status = ?, sources_count = ?,
                    received_count = ?, inserted_count = ?, vacancies_count = ?,
                    rejected_count = ?, duplicates_count = ?, errors_count = ?,
                    error_message = ?
                WHERE id = ?
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    "failed" if error else "completed",
                    stats.get("sources", 0),
                    stats.get("received", 0),
                    stats.get("inserted", 0),
                    stats.get("vacancies", 0),
                    stats.get("rejected", 0),
                    stats.get("duplicates", 0),
                    stats.get("errors", 0),
                    error,
                    run_id,
                ),
            )

    def statistics(self) -> dict[str, Any]:
        with self.connect() as connection:
            totals = connection.execute(
                """
                SELECT
                    COUNT(*) AS messages,
                    COALESCE(SUM(classification = 'vacancy' AND duplicate_of_id IS NULL), 0) AS vacancies,
                    COALESCE(SUM(duplicate_of_id IS NOT NULL), 0) AS duplicates,
                    COALESCE(SUM(classification NOT IN ('vacancy')), 0) AS rejected,
                    COUNT(DISTINCT channel_id) AS sources,
                    MIN(published_at) AS oldest,
                    MAX(published_at) AS newest
                FROM messages
                """
            ).fetchone()
            classes = connection.execute(
                "SELECT classification, COUNT(*) AS count FROM messages GROUP BY classification"
            ).fetchall()
            last_run = connection.execute(
                "SELECT * FROM collection_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return {
            "totals": dict(totals) if totals else {},
            "classifications": {row["classification"]: row["count"] for row in classes},
            "last_run": dict(last_run) if last_run else None,
        }

    def export_vacancies(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM vacancies ORDER BY published_at DESC, id DESC"
            ).fetchall()

        result = []
        for row in rows:
            item = dict(row)
            item["links"] = json.loads(item.pop("links_json"))
            item["has_media"] = bool(item["has_media"])
            result.append(item)
        return result
