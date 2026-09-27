from types import SimpleNamespace

from job_monitor.telegram import public_source_url


def test_public_source_url():
    assert (
        public_source_url(SimpleNamespace(username="qa_jobs"))
        == "https://t.me/qa_jobs"
    )


def test_public_source_url_is_none_for_private_source():
    assert public_source_url(SimpleNamespace(username=None)) is None
