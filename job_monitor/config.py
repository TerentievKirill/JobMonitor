import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    api_id: int | None
    api_hash: str | None
    phone: str | None
    auth_mode: str
    folder_name: str
    session_path: Path
    database_path: Path
    initial_hours_back: int
    initial_max_messages_per_chat: int
    max_messages_per_chat_per_run: int
    poll_interval_seconds: int
    store_raw_json: bool
    log_level: str

    @classmethod
    def load(cls) -> "Config":
        load_dotenv()
        api_id_value = os.getenv("TELEGRAM_API_ID")
        return cls(
            api_id=int(api_id_value) if api_id_value else None,
            api_hash=os.getenv("TELEGRAM_API_HASH") or None,
            phone=os.getenv("TELEGRAM_PHONE") or None,
            auth_mode=os.getenv("TELEGRAM_AUTH_MODE", "qr").casefold(),
            folder_name=os.getenv("TELEGRAM_FOLDER", "Поиск работы"),
            session_path=Path(os.getenv("TELEGRAM_SESSION", "data/collector")),
            database_path=Path(os.getenv("DATABASE_PATH", "data/vacancies.db")),
            initial_hours_back=int(os.getenv("INITIAL_HOURS_BACK", "72")),
            initial_max_messages_per_chat=int(
                os.getenv("INITIAL_MAX_MESSAGES_PER_CHAT", "500")
            ),
            max_messages_per_chat_per_run=int(
                os.getenv("MAX_MESSAGES_PER_CHAT_PER_RUN", "1000")
            ),
            poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "3600")),
            store_raw_json=os.getenv("STORE_RAW_JSON", "true").casefold()
            in {"1", "true", "yes", "on"},
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )

    def validate_telegram(self) -> None:
        if self.api_id is None:
            raise RuntimeError("Не заполнена переменная TELEGRAM_API_ID в .env")
        if not self.api_hash:
            raise RuntimeError("Не заполнена переменная TELEGRAM_API_HASH в .env")
        if self.auth_mode not in {"qr", "phone"}:
            raise RuntimeError("TELEGRAM_AUTH_MODE должен быть qr или phone")

        for name, value in (
            ("INITIAL_HOURS_BACK", self.initial_hours_back),
            ("INITIAL_MAX_MESSAGES_PER_CHAT", self.initial_max_messages_per_chat),
            ("MAX_MESSAGES_PER_CHAT_PER_RUN", self.max_messages_per_chat_per_run),
            ("POLL_INTERVAL_SECONDS", self.poll_interval_seconds),
        ):
            if value <= 0:
                raise RuntimeError(f"{name} должен быть больше нуля")
