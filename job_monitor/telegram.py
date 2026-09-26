import asyncio
import getpass
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import qrcode
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.messages import GetDialogFiltersRequest
from telethon.utils import get_peer_id

from .config import Config
from .database import Database
from .filters import classify, fingerprint


logger = logging.getLogger("job-monitor")


def folder_title(dialog_filter: Any) -> str:
    title = getattr(dialog_filter, "title", "")
    return getattr(title, "text", title) or ""


def extract_links(message: Any) -> list[str]:
    links: set[str] = set()
    for entity, visible_text in message.get_entities_text() or []:
        explicit_url = getattr(entity, "url", None)
        if explicit_url:
            links.add(explicit_url)
        elif visible_text.startswith(("http://", "https://", "tg://")):
            links.add(visible_text)

    for row in message.buttons or []:
        for button in row:
            url = getattr(button, "url", None)
            if url:
                links.add(url)
    return sorted(links)


def public_message_url(entity: Any, message_id: int) -> str | None:
    username = getattr(entity, "username", None)
    return f"https://t.me/{username}/{message_id}" if username else None


async def authorize(client: TelegramClient, config: Config) -> None:
    await client.connect()
    if await client.is_user_authorized():
        return

    if config.auth_mode == "phone":
        await client.start(phone=config.phone)
        return

    logger.info("Открой Telegram: Настройки → Устройства → Подключить устройство")
    logger.info("Отсканируй QR-код из консоли")
    while not await client.is_user_authorized():
        qr_login = await client.qr_login()
        qr = qrcode.QRCode(border=1)
        qr.add_data(qr_login.url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
        try:
            await qr_login.wait()
        except asyncio.TimeoutError:
            logger.info("QR-код истёк, создаю новый")
        except SessionPasswordNeededError:
            password = getpass.getpass("Пароль двухфакторной авторизации: ")
            await client.sign_in(password=password)


async def get_folder_entities(
    client: TelegramClient,
    wanted_folder_name: str,
) -> list[Any]:
    response = await client(GetDialogFiltersRequest())
    filters = getattr(response, "filters", response)
    available = [folder_title(item) for item in filters if folder_title(item)]
    selected = next(
        (
            item
            for item in filters
            if folder_title(item).casefold() == wanted_folder_name.casefold()
        ),
        None,
    )
    if selected is None:
        raise RuntimeError(
            f"Папка {wanted_folder_name!r} не найдена. "
            f"Доступные: {', '.join(available) or 'нет'}"
        )

    peers = [
        *getattr(selected, "pinned_peers", []),
        *getattr(selected, "include_peers", []),
    ]
    entities: list[Any] = []
    seen_ids: set[int] = set()
    for peer in peers:
        try:
            entity = await client.get_entity(peer)
            peer_id = get_peer_id(entity)
            if peer_id not in seen_ids:
                seen_ids.add(peer_id)
                entities.append(entity)
        except Exception:
            logger.exception("Не удалось получить источник %r", peer)

    if not entities:
        raise RuntimeError("В папке нет явно добавленных каналов или групп")
    return entities


def message_record(entity: Any, message: Any, store_raw_json: bool) -> dict[str, Any]:
    text = message.raw_text or ""
    filter_result = classify(text)
    published_at = message.date
    edited_at = message.edit_date
    return {
        "channel_id": get_peer_id(entity),
        "message_id": message.id,
        "channel_title": getattr(entity, "title", None) or str(getattr(entity, "id", "")),
        "channel_username": getattr(entity, "username", None),
        "published_at": published_at.astimezone(timezone.utc).isoformat()
        if published_at
        else None,
        "edited_at": edited_at.astimezone(timezone.utc).isoformat() if edited_at else None,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "text": text,
        "links_json": json.dumps(extract_links(message), ensure_ascii=False),
        "telegram_url": public_message_url(entity, message.id),
        "has_media": int(message.media is not None),
        "is_forwarded": int(message.forward is not None),
        "views": message.views,
        "forwards": message.forwards,
        "raw_json": message.to_json() if store_raw_json else None,
        "fingerprint": fingerprint(text),
        "classification": filter_result.classification,
        "filter_reason": filter_result.reason,
    }


async def messages_to_collect(
    client: TelegramClient,
    entity: Any,
    last_message_id: int | None,
    config: Config,
) -> list[Any]:
    if last_message_id is not None:
        return [
            message
            async for message in client.iter_messages(
                entity,
                min_id=last_message_id,
                reverse=True,
                limit=config.max_messages_per_chat_per_run,
            )
        ]

    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.initial_hours_back)
    newest_first = []
    async for message in client.iter_messages(
        entity,
        limit=config.initial_max_messages_per_chat,
    ):
        if message.date and message.date < cutoff:
            break
        newest_first.append(message)
    return list(reversed(newest_first))


async def collect_once(config: Config, database: Database) -> dict[str, int]:
    config.validate_telegram()
    config.session_path.parent.mkdir(parents=True, exist_ok=True)
    database.initialize()
    stats = {
        "sources": 0,
        "received": 0,
        "inserted": 0,
        "vacancies": 0,
        "rejected": 0,
        "duplicates": 0,
        "errors": 0,
    }
    run_id = database.start_run()
    client = TelegramClient(str(config.session_path), config.api_id, config.api_hash)

    try:
        await authorize(client, config)
        me = await client.get_me()
        logger.info("Авторизация успешна: account_id=%s", me.id)
        entities = await get_folder_entities(client, config.folder_name)
        stats["sources"] = len(entities)
        logger.info("Папка %r: источников — %d", config.folder_name, len(entities))

        for index, entity in enumerate(entities, start=1):
            title = getattr(entity, "title", None) or str(getattr(entity, "id", ""))
            channel_id = get_peer_id(entity)
            source_received = 0
            source_inserted = 0
            try:
                last_id = database.last_message_id(channel_id)
                messages = await messages_to_collect(client, entity, last_id, config)
                source_received = len(messages)
                stats["received"] += source_received

                for message in messages:
                    result = database.insert_message(
                        message_record(entity, message, config.store_raw_json)
                    )
                    if not result.inserted:
                        continue
                    source_inserted += 1
                    stats["inserted"] += 1
                    if result.duplicate:
                        stats["duplicates"] += 1
                    elif result.classification == "vacancy":
                        stats["vacancies"] += 1
                    else:
                        stats["rejected"] += 1

                logger.info(
                    "[%d/%d] %s: получено=%d, добавлено=%d",
                    index,
                    len(entities),
                    title,
                    source_received,
                    source_inserted,
                )
            except Exception:
                stats["errors"] += 1
                logger.exception("[%d/%d] Ошибка чтения %s", index, len(entities), title)

        database.finish_run(run_id, stats)
        logger.info(
            "Готово: добавлено=%d, вакансий=%d, мусора=%d, дублей=%d, ошибок=%d",
            stats["inserted"],
            stats["vacancies"],
            stats["rejected"],
            stats["duplicates"],
            stats["errors"],
        )
        return stats
    except Exception as error:
        database.finish_run(run_id, stats, error=str(error))
        raise
    finally:
        await client.disconnect()
