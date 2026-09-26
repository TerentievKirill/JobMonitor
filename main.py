import argparse
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from telethon import TelegramClient

from job_monitor.config import Config
from job_monitor.database import Database
from job_monitor.service import run_forever
from job_monitor.telegram import authorize, collect_once


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    logging.getLogger("telethon").setLevel(logging.WARNING)


def export_json(database: Database, output: Path) -> None:
    vacancies = database.export_vacancies()
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "vacancies_count": len(vacancies),
        "vacancies": vacancies,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Экспортировано вакансий: {len(vacancies)}")
    print(f"Результат: {output.resolve()}")


async def authenticate(config: Config) -> None:
    config.validate_telegram()
    config.session_path.parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(str(config.session_path), config.api_id, config.api_hash)
    try:
        await authorize(client, config)
        me = await client.get_me()
        print(f"Авторизация успешна: account_id={me.id}")
        print(f"Сессия: {config.session_path.resolve()}.session")
    finally:
        await client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="Сборщик вакансий из Telegram")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("auth", help="Создать Telegram-сессию")
    subparsers.add_parser("collect-once", help="Выполнить один сбор")
    subparsers.add_parser("run", help="Запустить постоянный сбор")
    subparsers.add_parser("stats", help="Показать статистику SQLite")
    export_parser = subparsers.add_parser("export", help="Экспортировать view vacancies")
    export_parser.add_argument(
        "-o", "--output", type=Path, default=Path("data/vacancies.json")
    )
    args = parser.parse_args()

    config = Config.load()
    configure_logging(config.log_level)
    database = Database(config.database_path)
    database.initialize()

    if args.command == "auth":
        asyncio.run(authenticate(config))
    elif args.command == "collect-once":
        asyncio.run(collect_once(config, database))
    elif args.command == "run":
        try:
            asyncio.run(run_forever(config, database))
        except KeyboardInterrupt:
            print("Сборщик остановлен")
    elif args.command == "stats":
        print(json.dumps(database.statistics(), ensure_ascii=False, indent=2))
    elif args.command == "export":
        export_json(database, args.output)


if __name__ == "__main__":
    main()
