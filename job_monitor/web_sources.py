"""Collect external job boards and enrich short Telegram job announcements."""
import hashlib
import ipaddress
import json
import logging
import re
import socket
from datetime import datetime, timezone
from html import unescape
from urllib.parse import urljoin, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

from .filters import classify, fingerprint

log = logging.getLogger("job-monitor")
FEEDS = {
    "ElixirJobs.net": "https://elixirjobs.net/rss",
    "Rails Job Board": "https://jobs.rubyonrails.org/jobs.rss",
}
WFA_URL = "https://workfromanywhere.app/remote-ruby-jobs"
MAX_BYTES = 1_000_000
MAX_TEXT = 12_000
TIMEOUT = 12


def safe_url(url):
    p = urlparse(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.port not in (None, 443):
        return False
    if p.hostname in {"localhost"} or p.hostname.endswith((".local", ".internal")):
        return False
    try:
        addresses = socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)
        return bool(addresses) and all(
            ipaddress.ip_address(addr[4][0]).is_global for addr in addresses
        )
    except (OSError, ValueError):
        return False


class SafeRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not safe_url(newurl):
            raise ValueError("Unsafe redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    if not safe_url(url):
        raise ValueError("Unsafe external URL")
    opener = build_opener(SafeRedirects)
    request = Request(url, headers={"User-Agent": "JobMonitor/1.0 (+job listings)"})
    with opener.open(request, timeout=TIMEOUT) as response:
        content_type = response.headers.get("Content-Type", "").lower()
        if not any(kind in content_type for kind in ("html", "xml", "rss", "text/plain")):
            raise ValueError("Unsupported content type")
        data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("Page too large")
        return data.decode("utf-8", errors="replace")


def html_text(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    return re.sub(r"\n{3,}", "\n\n", main.get_text("\n", strip=True))[:MAX_TEXT]


def feed_items(xml):
    root = ET.fromstring(xml)
    result = []
    for item in root.findall(".//item"):
        title = item.findtext("title") or ""
        url = item.findtext("link") or ""
        description = item.findtext("description") or ""
        result.append((title, url, html_text(unescape(description))))
    return result


def wfa_items(html):
    soup = BeautifulSoup(html, "html.parser")
    result = []
    # Job cards link to individual vacancy pages; exclude navigation and taxonomy links.
    for link in soup.select('a[href]'):
        href = urljoin(WFA_URL, link["href"])
        path = urlparse(href).path
        if not (path.startswith("/jobs/") or path.startswith("/job/")):
            continue
        title = link.get_text(" ", strip=True)
        if title:
            result.append((title, href, title))
    return list(dict(((url, (title, url, summary)) for title, url, summary in result)).values())


def record(source, url, title, text):
    now = datetime.now(timezone.utc).isoformat()
    key = hashlib.sha256(url.encode()).hexdigest()
    body = f"{title}\n{text}\nOriginal vacancy: {url}"
    result = classify(body)
    return {
        "channel_id": -int(hashlib.sha256(source.encode()).hexdigest()[:14], 16),
        "message_id": int(key[:14], 16),
        "channel_title": source,
        "channel_username": None,
        "published_at": now,
        "edited_at": None,
        "collected_at": now,
        "text": body,
        "links_json": json.dumps([url]),
        "telegram_url": None,
        "has_media": 0,
        "is_forwarded": 0,
        "views": None,
        "forwards": None,
        "raw_json": None,
        "fingerprint": fingerprint(body),
        "classification": result.classification,
        "filter_reason": result.reason,
    }


def collect_web(database):
    count = 0
    sources = {**FEEDS, "Work From Anywhere — Ruby": WFA_URL}
    for source, url in sources.items():
        try:
            raw = fetch(url)
            items = wfa_items(raw) if source.startswith("Work From") else feed_items(raw)
            for title, link, description in items:
                if not safe_url(link):
                    continue
                try:
                    detail = html_text(fetch(link))
                except Exception as exc:
                    log.warning("Cannot open %s: %s", link, exc)
                    detail = description
                if database.insert_message(record(source, link, title, detail)).inserted:
                    count += 1
            log.info("%s: %d listings", source, len(items))
        except Exception:
            log.exception("Cannot collect %s", source)
    return count


def enrich(vacancy):
    """Return a copy with external vacancy text; keep the original when fetching fails."""
    result = dict(vacancy)
    urls = list(vacancy.get("links") or [])
    urls += re.findall(r"https://[^\s<>\]\)]+", vacancy.get("text", ""))
    seen = set()
    for url in urls:
        url = url.rstrip(".,;")
        host = (urlparse(url).hostname or "").lower()
        if url in seen or host in {"t.me", "telegram.me"} or not safe_url(url):
            continue
        seen.add(url)
        try:
            detail = html_text(fetch(url))
            if len(detail) >= 120:
                result["text"] = (vacancy["text"] + "\n\n[EXTERNAL JOB DESCRIPTION]\n" + detail)[:18000]
                result["external_url"] = url
                break
        except Exception as exc:
            log.info("External link unavailable %s: %s", url, exc)
    return result
