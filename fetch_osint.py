#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from common import (
    CYBER_KEYWORDS,
    LOG_DIR,
    RELEVANCE_KEYWORDS,
    USER_AGENT,
    configure_logging,
    ensure_directories,
    iso_now,
    normalize_space,
    output_paths,
    parse_datetime_value,
    parse_run_date,
    reference_anchor,
    strip_html,
    title_similarity,
    write_json,
)

LOGGER = configure_logging("fetch_osint", LOG_DIR / "pipeline.log")

RSS_SOURCES = [
    {
        "source_id": "DOD",
        "tier": 1,
        "feed_url": "https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945&max=10",
    },
    {"source_id": "REUTERS", "tier": 2, "feed_url": "https://feeds.reuters.com/Reuters/worldNews"},
    {"source_id": "AP", "tier": 2, "feed_url": "https://rsshub.app/apnews/topics/politics"},
    {"source_id": "MILTIMES", "tier": 2, "feed_url": "https://www.militarytimes.com/arc/outboundfeeds/rss/"},
    {"source_id": "BREAKDEF", "tier": 2, "feed_url": "https://breakingdefense.com/feed/"},
    {"source_id": "WARZONE", "tier": 3, "feed_url": "https://www.thedrive.com/the-war-zone/rss"},
    {"source_id": "CNN", "tier": 2, "feed_url": "https://rss.cnn.com/rss/edition.rss"},
    {"source_id": "DEFONE", "tier": 3, "feed_url": "https://www.defenseone.com/rss/all/"},
    {"source_id": "SOFNEWS", "tier": 3, "feed_url": "https://sof.news/feed/"},
]


def require_requests():
    try:
        import requests
    except ImportError as exc:  # pragma: no cover - runtime guidance
        raise RuntimeError("requests is not installed. Run `bash setup.sh` first.") from exc
    return requests


def require_feedparser():
    try:
        import feedparser
    except ImportError as exc:  # pragma: no cover - runtime guidance
        raise RuntimeError("feedparser is not installed. Run `bash setup.sh` first.") from exc
    return feedparser


def requests_session():
    requests = require_requests()
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return session


def is_relevant(title: str, summary: str, domain: str | None = None) -> bool:
    haystack = f"{title} {summary}".lower()
    keywords = list(RELEVANCE_KEYWORDS)
    if domain == "cyber":
        keywords.extend(CYBER_KEYWORDS)
    return any(keyword in haystack for keyword in keywords)


def in_window(published_at, run_date, hours: int) -> bool:
    if published_at is None:
        return False
    start = reference_anchor(run_date) - timedelta(hours=hours)
    return published_at >= start


def tidy_article(article: dict[str, Any]) -> dict[str, Any]:
    article["title"] = normalize_space(article.get("title", ""))
    article["summary"] = normalize_space(article.get("summary", ""))
    article["url"] = article.get("url", "").strip()
    return article


def parse_feed_entry(entry, source_id: str, tier: int, run_date, hours: int, domain: str | None = None):
    title = normalize_space(getattr(entry, "title", "") or entry.get("title", ""))
    summary = strip_html(
        getattr(entry, "summary", "")
        or entry.get("summary", "")
        or entry.get("description", "")
        or ""
    )
    if not is_relevant(title, summary, domain=domain):
        return None

    published = (
        parse_datetime_value(getattr(entry, "published_parsed", None))
        or parse_datetime_value(getattr(entry, "updated_parsed", None))
        or parse_datetime_value(getattr(entry, "published", None))
        or parse_datetime_value(getattr(entry, "updated", None))
    )
    if not in_window(published, run_date, hours):
        return None

    url = getattr(entry, "link", "") or entry.get("link", "")
    if not url:
        return None

    article = {
        "tier": tier,
        "source_id": source_id,
        "title": title,
        "url": url,
        "summary": summary,
        "published": published.isoformat(),
    }
    if domain:
        article["domain"] = domain
    return tidy_article(article)


def fetch_rss_source(session, feedparser, config: dict[str, Any], run_date, hours: int, domain: str | None = None):
    try:
        response = session.get(config["feed_url"], timeout=20)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
    except Exception as exc:
        LOGGER.warning("RSS fetch failed for %s: %s", config["source_id"], exc)
        return []

    items = []
    for entry in getattr(feed, "entries", []):
        article = parse_feed_entry(entry, config["source_id"], config["tier"], run_date, hours, domain=domain)
        if article:
            items.append(article)
    return items


def extract_meta(html: str, names: list[str]) -> str:
    for name in names:
        pattern = rf'<meta[^>]+(?:name|property)=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']+)'
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return strip_html(match.group(1))
    return ""


def extract_title(html: str) -> str:
    for pattern in (
        r"<h1[^>]*>(.*?)</h1>",
        r"<title[^>]*>(.*?)</title>",
    ):
        match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return strip_html(match.group(1))
    return ""


def extract_first_paragraph(html: str) -> str:
    for match in re.finditer(r"<p[^>]*>(.*?)</p>", html, flags=re.IGNORECASE | re.DOTALL):
        text = strip_html(match.group(1))
        if len(text) > 40:
            return text
    return ""


def extract_article_date(html: str) -> Any:
    patterns = (
        r'Statement\s*\|\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})',
        r'<time[^>]+datetime=["\']([^"\']+)["\']',
        r'"datePublished"\s*:\s*"([^"]+)"',
        r"([A-Za-z]+\s+\d{1,2},\s+\d{4})",
    )
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            parsed = parse_datetime_value(match.group(1))
            if parsed:
                return parsed
    return None


def fetch_article_page(session, url: str, source_id: str, tier: int, run_date, hours: int):
    parsed_url = urlparse(url)
    if "/page/" in parsed_url.path:
        return None

    try:
        response = session.get(url, timeout=20)
        response.raise_for_status()
    except Exception as exc:
        LOGGER.warning("Page fetch failed for %s (%s): %s", source_id, url, exc)
        return None

    html = response.text
    title = extract_meta(html, ["og:title", "twitter:title"]) or extract_title(html)
    summary = extract_meta(html, ["description", "og:description"]) or extract_first_paragraph(html)
    published = extract_article_date(html)

    generic_titles = (
        "releases archives",
        "briefings & statements",
        "briefings statements",
        "statements and releases",
    )
    if not title or any(token in title.lower() for token in generic_titles):
        return None
    if not title or not published:
        return None
    if not is_relevant(title, summary):
        return None
    if not in_window(published, run_date, hours):
        return None

    return tidy_article(
        {
            "tier": tier,
            "source_id": source_id,
            "title": title,
            "url": url,
            "summary": summary,
            "published": published.isoformat(),
        }
    )


def fetch_centcom_statements(session, run_date, hours: int):
    url = "https://www.centcom.mil/MEDIA/STATEMENTS/"
    try:
        response = session.get(url, timeout=20)
        response.raise_for_status()
    except Exception as exc:
        LOGGER.warning("CENTCOM statement page fetch failed: %s", exc)
        return []

    links = []
    for raw_link in re.findall(r'href=["\']([^"\']+/Statements-View/Article/\d+/[^"\']+)["\']', response.text):
        links.append(urljoin(url, raw_link))

    seen = set()
    articles = []
    for link in links:
        if link in seen:
            continue
        seen.add(link)
        article = fetch_article_page(session, link, "CENTCOM", 1, run_date, hours)
        if article:
            articles.append(article)
        if len(articles) >= 8:
            break
    return articles


def fetch_white_house_releases(session, run_date, hours: int):
    candidate_pages = [
        "https://www.whitehouse.gov/releases/",
        "https://www.whitehouse.gov/briefings-statements/",
        "https://www.whitehouse.gov/briefing-room/statements-releases/",
    ]

    links = []
    for url in candidate_pages:
        try:
            response = session.get(url, timeout=20)
            response.raise_for_status()
        except Exception as exc:
            LOGGER.warning("White House release page fetch failed for %s: %s", url, exc)
            continue

        for raw_link in re.findall(r'href=["\']([^"\']*whitehouse\.gov/[^"\']+|/[^"\']+)["\']', response.text):
            full_link = urljoin(url, raw_link)
            parsed = urlparse(full_link)
            if not any(token in parsed.path for token in ("/releases/", "/briefings-statements/", "/briefing-room/statements-releases/")):
                continue
            if parsed.path.rstrip("/") in {"/releases", "/briefings-statements", "/briefing-room/statements-releases"}:
                continue
            if "/page/" in parsed.path or full_link.rstrip("/") == url.rstrip("/"):
                continue
            links.append(full_link)

    seen = set()
    articles = []
    for link in links:
        if link in seen:
            continue
        seen.add(link)
        article = fetch_article_page(session, link, "TRUMP", 1, run_date, hours)
        if article:
            articles.append(article)
        if len(articles) >= 8:
            break
    return articles


def fetch_cisa_advisories(session, feedparser, run_date, hours: int = 48):
    config = {"source_id": "CISA", "tier": 1, "feed_url": "https://www.cisa.gov/cybersecurity-advisories/all.xml"}
    advisories = fetch_rss_source(session, feedparser, config, run_date, hours, domain="cyber")
    if advisories:
        return advisories

    fallback = {"source_id": "TENABLE", "tier": 3, "feed_url": "https://www.tenable.com/blog/feed"}
    return fetch_rss_source(session, feedparser, fallback, run_date, hours, domain="cyber")


def dedupe_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    for article in articles:
        if any(title_similarity(article["title"], existing["title"]) >= 0.7 for existing in deduped):
            continue
        deduped.append(article)
    return deduped


def collect_osint(run_date):
    feedparser = require_feedparser()
    session = requests_session()

    all_articles: list[dict[str, Any]] = []
    all_articles.extend(fetch_centcom_statements(session, run_date, 48))
    all_articles.extend(fetch_white_house_releases(session, run_date, 48))

    for config in RSS_SOURCES:
        all_articles.extend(fetch_rss_source(session, feedparser, config, run_date, 48))

    all_articles.extend(fetch_cisa_advisories(session, feedparser, run_date, 48))
    recent_24 = [item for item in all_articles if in_window(parse_datetime_value(item["published"]), run_date, 24)]
    selected = recent_24 if len(recent_24) >= 5 else all_articles

    selected = sorted(
        selected,
        key=lambda item: (
            item.get("tier", 9),
            -(parse_datetime_value(item.get("published")) or parse_datetime_value("1970-01-01")).timestamp(),
        ),
        reverse=False,
    )
    deduped = dedupe_articles(selected)

    payload = {
        "fetched_at": iso_now(),
        "articles": deduped,
    }
    return payload


def article_counts(payload: dict[str, Any]) -> Counter:
    counter = Counter()
    for article in payload.get("articles", []):
        counter[article["tier"]] += 1
    return counter


def save_osint(payload: dict[str, Any], run_date) -> Path:
    paths = output_paths(run_date)
    write_json(paths["osint_json"], payload)
    return paths["osint_json"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Epic Fury OSINT package.")
    parser.add_argument("--date", help="Run date in YYYY-MM-DD format")
    args = parser.parse_args()

    ensure_directories()
    run_date = parse_run_date(args.date)
    payload = collect_osint(run_date)
    save_path = save_osint(payload, run_date)
    counts = article_counts(payload)
    print(f"Tier 1: {counts.get(1, 0)}")
    print(f"Tier 2: {counts.get(2, 0)}")
    print(f"Tier 3: {counts.get(3, 0)}")
    LOGGER.info("Saved OSINT package to %s (%s articles)", save_path, len(payload.get("articles", [])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
