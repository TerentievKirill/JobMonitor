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

QA_ROLE_PATTERNS = (
    re.compile(r"(?i)(?<![\w])(?:qa|aqa|sdet)(?![\w])"),
    re.compile(r"(?i)\bquality\s+assurance\b"),
    re.compile(r"(?i)\b(?:test|testing|quality)\s+(?:automation\s+)?engineer\b"),
    re.compile(r"(?i)\b(?:software|manual|automation)\s+tester\b"),
    re.compile(r"(?i)\bтестировщик[а-яё]*\b"),
    re.compile(r"(?i)\b(?:инженер|специалист)[а-яё\s-]{0,30}\bтестирован[а-яё]*\b"),
)

PRIORITY_MARKERS = (
    (re.compile(r"(?i)(?<![\w])python(?![\w])"), 25),
    (re.compile(r"(?i)(?<![\w])pytest(?![\w])"), 20),
    (re.compile(r"(?i)\b(?:automation|автоматизац[а-яё]*)\b"), 20),
    (re.compile(r"(?i)(?<![\w])(?:api|rest|websocket)(?![\w])"), 12),
    (re.compile(r"(?i)(?<![\w])(?:gitlab|ci/cd|docker|kafka)(?![\w])"), 8),
    (re.compile(r"(?i)(?<![\w])(?:playwright|appium|allure)(?![\w])"), 10),
    (re.compile(r"(?i)\b(?:cyprus|limassol|кипр|лимасол)[а-яё]*\b"), 35),
    (re.compile(r"(?i)\b(?:remote|удален[а-яё]*|удалён[а-яё]*)\b"), 8),
    (re.compile(r"(?i)\b(?:senior|middle\+|mid\+|старш[а-яё]*)\b"), 8),
    (re.compile(r"(?i)\bjunior\b"), -25),
)


@dataclass(frozen=True)
class FilterResult:
    classification: str
    reason: str | None


def normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def fingerprint(text: str) -> str:
    return hashlib.sha256(normalized_text(text).encode("utf-8")).hexdigest()


def analysis_priority(text: str, profile: dict | None = None) -> int | None:
    """Preselect by actual technology, not generic backend job titles."""
    candidate = (profile or {}).get("candidate", {})
    keywords = candidate.get("search_keywords")
    if keywords:
        matches = {
            word.casefold()
            for word in keywords
            if re.search(r"(?i)(?<![\\w])" + re.escape(str(word)) + r"(?![\\w])", text)
        }
        if not matches:
            return None
        # Elixir/Phoenix is preferred; Ruby/Rails is also eligible.
        priority = 100 + 20 * len(matches)
        if matches & {"elixir", "phoenix"}:
            priority += 50
        if matches & {"ruby", "ruby on rails", "rails"}:
            priority += 20
        if re.search(r"(?i)\\b(?:remote|worldwide|global|удал[её]нн|relocation|contractor|b2b)\\b", text):
            priority += 8
        return priority
    if not any(pattern.search(text) for pattern in QA_ROLE_PATTERNS):
        return None
    score = 100
    for pattern, weight in PRIORITY_MARKERS:
        if pattern.search(text):
            score += weight
    return score


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
