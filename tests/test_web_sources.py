from job_monitor.filters import analysis_priority
from job_monitor.web_sources import feed_items, html_text, wfa_items


PROFILE = {"candidate": {"search_keywords": ["Elixir", "Phoenix", "Ruby", "Rails"]}}


def test_ivan_filter():
    assert analysis_priority("Senior Elixir Engineer", PROFILE) is not None
    assert analysis_priority("Ruby on Rails developer", PROFILE) is not None
    assert analysis_priority("QA Automation Python", PROFILE) is None


def test_feed_items():
    xml = """<rss><channel><item><title>Elixir Developer</title>
    <link>https://example.com/job/1</link>
    <description><![CDATA[<p>Remote Elixir role</p>]]></description>
    </item></channel></rss>"""
    assert feed_items(xml) == [("Elixir Developer", "https://example.com/job/1", "Remote Elixir role")]


def test_wfa_items():
    html = """<a href="/jobs/ruby-engineer-at-example">Ruby Engineer</a>
    <a href="/companies">Companies</a>"""
    rows = wfa_items(html)
    assert len(rows) == 1
    assert rows[0][1] == "https://workfromanywhere.app/jobs/ruby-engineer-at-example"


def test_html_text_removes_scripts():
    assert html_text("<main><h1>Ruby</h1><script>evil()</script><p>Remote</p></main>") == "Ruby\\nRemote"
