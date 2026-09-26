import asyncio
import logging

from .config import Config
from .database import Database
from .telegram import collect_once


logger = logging.getLogger("job-monitor")


async def run_forever(config: Config, database: Database) -> None:
    while True:
        try:
            await collect_once(config, database)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Цикл сбора завершился с ошибкой; повторим позже")

        logger.info("Следующий сбор через %d секунд", config.poll_interval_seconds)
        await asyncio.sleep(config.poll_interval_seconds)
