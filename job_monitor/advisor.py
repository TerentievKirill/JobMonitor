import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Literal

import yaml
from openai import BadRequestError, OpenAI
from pydantic import BaseModel, Field

from .config import Config
from .database import Database
from .filters import analysis_priority


logger = logging.getLogger("job-monitor")


class VacancyAssessment(BaseModel):
    message_row_id: int
    decision: Literal["recommended", "review", "skip"]
    score: int = Field(ge=0, le=100)
    title: str
    summary: str
    matches: list[str]
    gaps: list[str]
    reason: str
    language: Literal["ru", "en", "other"]
    contacts: list[str]
    application_links: list[str]


class AssessmentBatch(BaseModel):
    assessments: list[VacancyAssessment]


@dataclass(frozen=True)
class AnalysisRun:
    considered: int
    assessments: list[dict]
    locally_skipped: int = 0


SYSTEM_PROMPT = """You are a pragmatic job-search advisor for one QA automation engineer.
Evaluate only whether each vacancy is worth this candidate's time.
Do not require a perfect keyword match. Transferable experience counts.
Treat developing skills as acceptable gaps unless the vacancy explicitly requires deep production expertise.
Use 'recommended' when applying is sensible, 'review' when a human must verify important details,
and 'skip' only for a clear mismatch. Keep title, summary, matches, gaps, and reason concise.
Detect the vacancy language. Write title, summary, matches, gaps, and reason in that same language:
Russian vacancy means fully Russian assessment; English vacancy means English assessment.
Extract contacts verbatim (Telegram usernames, emails, phone numbers) and application links.
Do not invent or translate contacts and URLs. Return exactly one assessment for every supplied
message_row_id and never invent requirements."""


def load_profile(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as source:
        profile = yaml.safe_load(source)
    if not isinstance(profile, dict) or "candidate" not in profile:
        raise RuntimeError(f"Некорректный профиль: {path}")
    return profile


def chunks(items: list[dict], size: int) -> Iterable[list[dict]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def compact_vacancy(vacancy: dict) -> dict:
    return {
        "message_row_id": vacancy["id"],
        "published_at": vacancy["published_at"],
        "source": vacancy["channel_title"],
        "url": vacancy["telegram_url"] or (vacancy["links"][0] if vacancy["links"] else None),
        "links": vacancy["links"],
        "text": vacancy["text"][:6000],
    }


def obvious_contacts(vacancy: dict) -> list[str]:
    text = vacancy["text"]
    contacts = set(re.findall(r"(?<![\w@])@[A-Za-z0-9_]{5,32}", text))
    contacts.update(
        re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    )
    for link in vacancy["links"]:
        if "t.me/" in link and link != vacancy["telegram_url"]:
            contacts.add(link)
    return sorted(contacts)


def request_assessments(client: OpenAI, model: str, profile: dict, batch: list[dict]) -> list[VacancyAssessment]:
    user_payload = {
        "candidate_profile": profile,
        "vacancies": [compact_vacancy(vacancy) for vacancy in batch],
    }
    try:
        response = client.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            response_format=AssessmentBatch,
        )
    except BadRequestError as error:
        if "json_validate_failed" not in str(error) or len(batch) == 1:
            raise
        middle = len(batch) // 2
        logger.warning(
            "Groq вернул некорректный JSON; дробим пакет из %d вакансий",
            len(batch),
        )
        return request_assessments(client, model, profile, batch[:middle]) + request_assessments(
            client, model, profile, batch[middle:]
        )

    parsed = response.choices[0].message.parsed
    if parsed is None:
        raise RuntimeError("Groq не вернул структурированный результат")
    return parsed.assessments


def analyze(config: Config, database: Database, *, reanalyze: bool = False) -> AnalysisRun:
    config.validate_analysis()
    profile = load_profile(config.profile_path)
    since = datetime.now(timezone.utc) - timedelta(hours=config.analysis_hours_back)
    pending = database.vacancies_for_analysis(
        since=since, limit=None, reanalyze=reanalyze
    )
    ranked: list[tuple[int, dict]] = []
    for vacancy in pending:
        priority = analysis_priority(vacancy["text"])
        if priority is not None:
            ranked.append((priority, vacancy))

    ranked.sort(
        key=lambda item: (
            -item[0],
            item[1]["published_at"] or item[1]["collected_at"],
            item[1]["id"],
        )
    )
    vacancies = [vacancy for _, vacancy in ranked[: config.analysis_limit]]
    locally_skipped = len(pending) - len(ranked)
    if not vacancies:
        return AnalysisRun(considered=0, assessments=[], locally_skipped=locally_skipped)

    client = OpenAI(
        api_key=config.groq_api_key,
        base_url="https://api.groq.com/openai/v1",
        timeout=180.0,
    )
    saved: list[dict] = []
    known_ids = {vacancy["id"] for vacancy in vacancies}

    batches = list(chunks(vacancies, config.analysis_batch_size))
    for batch_number, batch in enumerate(batches, start=1):
        assessments = request_assessments(client, config.ai_model, profile, batch)
        batch_ids = {vacancy["id"] for vacancy in batch}
        returned_ids = {item.message_row_id for item in assessments}
        if returned_ids != batch_ids or not returned_ids <= known_ids:
            raise RuntimeError(
                f"Groq вернул неверный набор ID: ожидались {sorted(batch_ids)}, "
                f"получены {sorted(returned_ids)}"
            )

        for item in assessments:
            data = item.model_dump()
            vacancy = next(v for v in batch if v["id"] == item.message_row_id)
            data["contacts"] = sorted(set(data["contacts"]) | set(obvious_contacts(vacancy)))
            database.save_analysis(item.message_row_id, data, config.ai_model)
            data["url"] = vacancy["telegram_url"] or (
                vacancy["links"][0] if vacancy["links"] else None
            )
            data["source"] = vacancy["channel_title"]
            saved.append(data)

        if batch_number < len(batches):
            logger.info(
                "Пакет %d/%d готов; пауза %d секунд для лимита Groq",
                batch_number,
                len(batches),
                config.analysis_pause_seconds,
            )
            time.sleep(config.analysis_pause_seconds)

    return AnalysisRun(
        considered=len(vacancies),
        assessments=saved,
        locally_skipped=locally_skipped,
    )


def write_report(run: AnalysisRun, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(run.assessments, key=lambda item: item["score"], reverse=True)
    counts = {
        decision: sum(item["decision"] == decision for item in ordered)
        for decision in ("recommended", "review", "skip")
    }
    lines = [
        f"# Подборка вакансий — {datetime.now().astimezone():%d.%m.%Y}",
        "",
        f"Проанализировано: **{run.considered}**",
        f"Не отправлено в Groq локальным фильтром: **{run.locally_skipped}**",
        f"Стоит откликнуться: **{counts['recommended']}** · "
        f"Посмотреть глазами: **{counts['review']}** · "
        f"Пропустить: **{counts['skip']}**",
        "",
    ]

    sections = (
        ("recommended", "🔥 Стоит откликнуться"),
        ("review", "🔎 Посмотреть глазами"),
        ("skip", "⛔ Пропустить"),
    )
    for decision, heading in sections:
        items = [item for item in ordered if item["decision"] == decision]
        if not items:
            continue
        lines.extend([f"## {heading}", ""])
        for item in items:
            lines.extend(
                [
                    f"### {item['title']} — {item['score']}%",
                    "",
                    item["summary"],
                    "",
                    f"**Совпадает:** {', '.join(item['matches']) or '—'}",
                    "",
                    f"**Пробелы/риски:** {', '.join(item['gaps']) or '—'}",
                    "",
                    f"**Вывод:** {item['reason']}",
                    "",
                    f"**Источник:** {item['source']}",
                ]
            )
            contacts = item.get("contacts", [])
            if contacts:
                formatted_contacts = [
                    f"[{contact}](https://t.me/{contact[1:]})" if contact.startswith("@") else contact
                    for contact in contacts
                ]
                lines.append(f"**Контакты:** {', '.join(formatted_contacts)}")
            application_links = item.get("application_links", [])
            if application_links:
                lines.append(
                    "**Отклик:** "
                    + ", ".join(f"[ссылка {index}]({link})" for index, link in enumerate(application_links, 1))
                )
            if item["url"]:
                lines.append(f"**Ссылка:** {item['url']}")
            lines.extend(["", "---", ""])

    if not ordered:
        lines.append("Новых вакансий для анализа за выбранный период нет.")
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
