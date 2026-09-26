import hashlib
import re
from dataclasses import dataclass


RESUME_MARKERS = re.compile(r"(?i)(?:^|\s)#(?:cv|resume|резюме)\b")
ADVERTISEMENT_MARKERS = ("#реклама", "о рекламодателе")
ARTICLE_MARKERS = ("кто виноват, если кандидат",)
HIRING_MARKERS = (
    "откликнуться",
    "от кандидата",
    "требования",
    "обязанности",
    "чем предстоит",
    "we're hiring",
    "we are hiring",
    "ищем ",
)


@dataclass(frozen=True)
class FilterResult:
    classification: str
    reason: str | None


def normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def fingerprint(text: str) -> str:
    return hashlib.sha256(normalized_text(text).encode("utf-8")).hexdigest()


def classify(text: str) -> FilterResult:
    lowered = text.casefold()

    if not text.strip():
        return FilterResult("empty", "empty_text")

    if RESUME_MARKERS.search(text):
        return FilterResult("resume", "resume_hashtag")

    if any(marker in lowered for marker in ADVERTISEMENT_MARKERS):
        return FilterResult("advertisement", "explicit_advertisement_marker")

    course_ad = (
        re.search(r"(?i)\bкурс[а-яё]*\b", text)
        and any(marker in lowered for marker in ("обучен", "записат", "программа курса"))
        and "ваканси" not in lowered
        and not any(marker in lowered for marker in HIRING_MARKERS)
    )
    if course_ad:
        return FilterResult("advertisement", "course_advertisement")

    if any(marker in lowered for marker in ARTICLE_MARKERS):
        return FilterResult("article", "editorial_post")

    # Консервативный принцип MVP: всё сомнительное считаем кандидатом в вакансии.
    return FilterResult("vacancy", None)
