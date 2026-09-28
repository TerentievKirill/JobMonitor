import argparse
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from telethon import TelegramClient

from job_monitor.config import Config
from job_monitor.advisor import analyze, write_report
from job_monitor.database import Database
from job_monitor.service import run_forever
from job_monitor.telegram import authorize, collect_once, export_source_links


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
    sources_parser = subparsers.add_parser(
        "sources", help="Сохранить публичные ссылки на источники из Telegram-папки"
    )
    sources_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("data/telegram_sources.txt"),
        help="Файл результата (по умолчанию data/telegram_sources.txt)",
    )
    analyze_parser = subparsers.add_parser("analyze", help="Оценить новые вакансии через Groq")
    analyze_parser.add_argument(
        "--reanalyze", action="store_true", help="Повторно оценить вакансии за выбранный период"
    )
    daily_parser = subparsers.add_parser(
        "daily", help="Собрать вакансии, оценить их и создать отчёт"
    )
    daily_parser.add_argument(
        "--reanalyze", action="store_true", help="Повторно оценить вакансии за выбранный период"
    )
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
    elif args.command == "sources":
        stats = asyncio.run(export_source_links(config, args.output))
        print(f"Источников в папке: {stats['sources']}")
        print(f"Публичных ссылок: {stats['public']}")
        if stats["private"]:
            print(f"Без публичной ссылки: {stats['private']}")
        print(f"Результат: {args.output.resolve()}")
    elif args.command == "analyze":
        run = analyze(config, database, reanalyze=args.reanalyze)
        write_report(run, config.report_path)
        print(f"Проанализировано вакансий: {run.considered}")
        print(f"Не отправлено в Groq локальным фильтром: {run.locally_skipped}")
        print(f"Отчёт: {config.report_path.resolve()}")
    elif args.command == "daily":
        asyncio.run(collect_once(config, database))
        run = analyze(config, database, reanalyze=args.reanalyze)
        write_report(run, config.report_path)
        print(f"Проанализировано вакансий: {run.considered}")
        print(f"Не отправлено в Groq локальным фильтром: {run.locally_skipped}")
        print(f"Отчёт: {config.report_path.resolve()}")
    elif args.command == "export":
        export_json(database, args.output)


if __name__ == "__main__":
    main()
