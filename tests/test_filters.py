from job_monitor.filters import analysis_priority, classify


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


def test_non_qa_vacancy_is_not_sent_to_analysis():
    assert analysis_priority("Senior Golang Developer. Remote") is None


def test_fullstack_qa_in_cyprus_gets_high_priority():
    text = (
        "Fullstack QA Engineer, Limassol, Cyprus. Python, pytest, Appium, "
        "GitLab CI, backend and frontend automation."
    )
    assert analysis_priority(text) >= 200


def test_russian_test_engineer_is_analysis_candidate():
    assert analysis_priority("Инженер по тестированию, Python и REST API") is not None
