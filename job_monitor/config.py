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
    groq_api_key: str | None
    ai_model: str
    profile_path: Path
    report_path: Path
    analysis_hours_back: int
    analysis_limit: int
    analysis_batch_size: int
    analysis_pause_seconds: int

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
            groq_api_key=os.getenv("GROQ_API_KEY") or None,
            ai_model=os.getenv("AI_MODEL", "openai/gpt-oss-120b"),
            profile_path=Path(os.getenv("PROFILE_PATH", "profile.yaml")),
            report_path=Path(os.getenv("REPORT_PATH", "data/daily_report.md")),
            analysis_hours_back=int(os.getenv("ANALYSIS_HOURS_BACK", "36")),
            analysis_limit=int(os.getenv("ANALYSIS_LIMIT", "50")),
            analysis_batch_size=int(os.getenv("ANALYSIS_BATCH_SIZE", "3")),
            analysis_pause_seconds=int(os.getenv("ANALYSIS_PAUSE_SECONDS", "20")),
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

    def validate_analysis(self) -> None:
        if not self.groq_api_key:
            raise RuntimeError("Не заполнена переменная GROQ_API_KEY в .env")
        if not self.profile_path.is_file():
            raise RuntimeError(f"Не найден профиль: {self.profile_path}")
        for name, value in (
            ("ANALYSIS_HOURS_BACK", self.analysis_hours_back),
            ("ANALYSIS_LIMIT", self.analysis_limit),
            ("ANALYSIS_BATCH_SIZE", self.analysis_batch_size),
            ("ANALYSIS_PAUSE_SECONDS", self.analysis_pause_seconds),
        ):
            if value <= 0:
                raise RuntimeError(f"{name} должен быть больше нуля")
