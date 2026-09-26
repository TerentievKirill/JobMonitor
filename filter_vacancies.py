import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from job_monitor.filters import classify, fingerprint


def rejection_reason(message: dict[str, Any], seen: set[str]) -> str | None:
    text = message.get("text", "")
    result = classify(text)
    if result.classification != "vacancy":
        return result.classification

    message_fingerprint = fingerprint(text)
    if message_fingerprint in seen:
        return "duplicate"

    seen.add(message_fingerprint)
    return None


def compact_record(message: dict[str, Any]) -> dict[str, Any]:
    channel_id = message["channel_id"]
    message_id = message["message_id"]
    return {
        "id": f"{channel_id}:{message_id}",
        "published_at": message.get("published_at"),
        "source": {
            "channel_id": channel_id,
            "channel_title": message.get("channel_title"),
            "channel_username": message.get("channel_username"),
            "message_id": message_id,
            "telegram_url": message.get("telegram_url"),
        },
        "text": message.get("text", ""),
        "links": message.get("links", []),
        "has_media": bool(message.get("has_media")),
        "views": message.get("views"),
        "fingerprint": fingerprint(message.get("text", "")),
    }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    messages = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(f"Некорректный JSON в строке {line_number}: {error}") from error
    return messages


def filter_messages(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Counter]:
    seen: set[str] = set()
    rejected: Counter = Counter()
    vacancies = []

    for message in messages:
        reason = rejection_reason(message, seen)
        if reason:
            rejected[reason] += 1
            continue
        vacancies.append(compact_record(message))

    return vacancies, rejected


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Удаляет из Telegram-выгрузки только очевидный мусор и точные дубли."
    )
    parser.add_argument("input", type=Path, help="Исходный messages.jsonl")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("data/vacancies.json"),
        help="Итоговый JSON",
    )
    args = parser.parse_args()

    messages = read_jsonl(args.input)
    vacancies, rejected = filter_messages(messages)
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filter_version": "mvp-1",
        "source_messages_count": len(messages),
        "vacancies_count": len(vacancies),
        "rejected_count": sum(rejected.values()),
        "rejected_by_reason": dict(sorted(rejected.items())),
        "vacancies": vacancies,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Исходных сообщений: {len(messages)}")
    print(f"Оставлено: {len(vacancies)}")
    print(f"Удалено: {sum(rejected.values())} — {dict(rejected)}")
    print(f"Результат: {args.output.resolve()}")


if __name__ == "__main__":
    main()
