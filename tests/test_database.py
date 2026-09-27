import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from job_monitor.database import Database
from job_monitor.filters import classify, fingerprint


def record(channel_id: int, message_id: int, text: str) -> dict:
    result = classify(text)
    return {
        "channel_id": channel_id,
        "message_id": message_id,
        "channel_title": f"channel-{channel_id}",
        "channel_username": None,
        "published_at": "2026-09-26T12:00:00+00:00",
        "edited_at": None,
        "collected_at": "2026-09-26T12:01:00+00:00",
        "text": text,
        "links_json": json.dumps(["https://example.com/job"]),
        "telegram_url": None,
        "has_media": 0,
        "is_forwarded": 0,
        "views": 10,
        "forwards": 0,
        "raw_json": None,
        "fingerprint": fingerprint(text),
        "classification": result.classification,
        "filter_reason": result.reason,
    }


def test_repeated_source_message_is_idempotent(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    item = record(-1001, 1, "Senior QA Engineer. Требования: Python")

    assert database.insert_message(item).inserted is True
    assert database.insert_message(item).inserted is False
    assert database.statistics()["totals"]["messages"] == 1


def test_same_text_from_another_channel_is_duplicate(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    text = "Senior QA Engineer. Требования: Python"

    first = database.insert_message(record(-1001, 1, text))
    second = database.insert_message(record(-1002, 20, text))

    assert first.duplicate is False
    assert second.duplicate is True
    assert len(database.export_vacancies()) == 1


def test_rejected_message_is_stored_but_hidden_from_vacancies(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    result = database.insert_message(record(-1001, 1, "#resume Senior QA, ищу работу"))

    assert result.inserted is True
    assert result.classification == "resume"
    assert database.statistics()["totals"]["messages"] == 1
    assert database.export_vacancies() == []


def test_analysis_is_saved_and_vacancy_is_not_selected_again(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    database.insert_message(record(-1001, 1, "Senior QA Engineer. Требования: Python"))
    since = datetime.now(timezone.utc) - timedelta(days=365)

    selected = database.vacancies_for_analysis(since=since, limit=10)
    assert len(selected) == 1

    database.save_analysis(
        selected[0]["id"],
        {
            "decision": "recommended",
            "score": 85,
            "title": "Senior QA Engineer",
            "summary": "Подходит",
            "matches": ["Python"],
            "gaps": [],
            "reason": "Совпадает основной стек",
        },
        "test-model",
    )

    assert database.vacancies_for_analysis(since=since, limit=10) == []
    assert len(database.vacancies_for_analysis(since=since, limit=10, reanalyze=True)) == 1
