"""Совместимый запуск одного сбора из первой версии проекта."""

import asyncio

from job_monitor.config import Config
from job_monitor.database import Database
from job_monitor.telegram import collect_once


if __name__ == "__main__":
    config = Config.load()
    asyncio.run(collect_once(config, Database(config.database_path)))
