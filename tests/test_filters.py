from job_monitor.filters import classify


def test_resume_is_rejected():
    result = classify("#CV Senior QA Engineer, ищу работу")
    assert result.classification == "resume"


def test_explicit_advertisement_is_rejected():
    result = classify("Курс тестировщика со скидкой. #реклама О рекламодателе")
    assert result.classification == "advertisement"


def test_course_in_benefits_does_not_reject_vacancy():
    text = (
        "Senior QA Engineer. Требования: Python. "
        "Откликнуться по ссылке. Бесплатные курсы английского языка."
    )
    assert classify(text).classification == "vacancy"


def test_unknown_content_is_kept_conservatively():
    assert classify("Нужен хороший специалист").classification == "vacancy"
