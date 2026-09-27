from pathlib import Path

from job_monitor.advisor import AnalysisRun, load_profile, write_report


def test_profile_is_valid():
    profile = load_profile(Path("profile.yaml"))
    assert "candidate" in profile
    assert "Python" in profile["candidate"]["strong_skills"]


def test_markdown_report_orders_best_score_first(tmp_path: Path):
    output = tmp_path / "report.md"
    run = AnalysisRun(
        considered=2,
        assessments=[
            {
                "decision": "review",
                "score": 55,
                "title": "QA Engineer",
                "summary": "Нужно проверить",
                "matches": ["API"],
                "gaps": ["English B2"],
                "reason": "Неясны условия",
                "source": "Channel A",
                "url": None,
            },
            {
                "decision": "recommended",
                "score": 91,
                "title": "Senior QA Automation",
                "summary": "Хорошее совпадение",
                "matches": ["Python", "pytest"],
                "gaps": [],
                "reason": "Подходит основной стек",
                "source": "Channel B",
                "url": "https://example.com/job",
            },
        ],
    )

    write_report(run, output)
    text = output.read_text(encoding="utf-8")

    assert "Стоит откликнуться: **1**" in text
    assert text.index("Senior QA Automation") < text.index("QA Engineer")
