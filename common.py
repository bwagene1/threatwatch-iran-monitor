#!/usr/bin/env python3
from __future__ import annotations

import calendar
import json
import logging
import os
import re
import sys
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any, Iterable

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - handled at runtime
    load_dotenv = None

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.10 ships zoneinfo
    ZoneInfo = None

PROJECT_DIR = Path(__file__).resolve().parent
THREATWATCH_ROOT = PROJECT_DIR.parent
SHARED_ENV_PATH = THREATWATCH_ROOT / ".env"

BRIEF_STARTER_PATH = Path(
    os.environ.get("TW_BRIEF_STARTER", str(PROJECT_DIR / "prompts" / "brief_starter.json"))
)
BRIEF_PROMPT_PATH = Path(
    os.environ.get("TW_BRIEF_PROMPT", str(PROJECT_DIR / "prompts" / "brief_writer_system.md"))
)
BRIEF_RENDERER_DIR = Path(
    os.environ.get("TW_RENDERER_DIR", str(PROJECT_DIR.parent / "brief-system"))
)
BRIEF_RENDERER_SCRIPT = BRIEF_RENDERER_DIR / "threatwatch_render.js"

OUTPUT_DIR = PROJECT_DIR / "output"
JSON_DIR = OUTPUT_DIR / "json"
DOCX_DIR = OUTPUT_DIR / "docx"
PDF_DIR = OUTPUT_DIR / "pdf"
MD_DIR = OUTPUT_DIR / "md"
HTML_DIR = OUTPUT_DIR / "html"
LOG_DIR = PROJECT_DIR / "logs"
DASHBOARD_DIR = PROJECT_DIR / "dashboard"
CLIENTS_PATH = PROJECT_DIR / "clients.json"

EVENT_TITLE = "OPERATION EPIC FURY"
PRODUCT_NAME = "ThreatWatch AI"
CLASSIFICATION = "Open-source intelligence only  |  Not for redistribution"
AUDIENCE = "Security/executive leadership, travel, supply chain, business continuity"
EVENT_START_DATE = date(2026, 2, 28)
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

RELEVANCE_KEYWORDS = [
    "iran",
    "epic fury",
    "hormuz",
    "centcom",
    "persian gulf",
    "tehran",
    "irgc",
    "f-15",
    "nuclear",
]
CYBER_KEYWORDS = [
    "iran",
    "muddy",
    "manticore",
    "handala",
    "irgc",
    "apt34",
    "apt33",
    "apt35",
    "oilrig",
    "charming kitten",
]
PLACEHOLDER_PATTERNS = ("REPLACE:", "TBD", "LOREM", "SIMULATED")

BUILTIN_SOURCES = {
    "CENTCOM": {"tier": 1, "label": "CENTCOM official statement"},
    "IDF": {"tier": 1, "label": "IDF official statement"},
    "TRUMP": {"tier": 1, "label": "White House / presidential statement"},
    "IRAN_STATE": {"tier": 1, "label": "Iranian state media (IRNA/IRIB)"},
    "REUTERS": {"tier": 2, "label": "Reuters"},
    "AP": {"tier": 2, "label": "AP"},
    "CNN": {"tier": 2, "label": "CNN"},
    "NBC": {"tier": 2, "label": "NBC News"},
    "CNBC": {"tier": 2, "label": "CNBC"},
    "BBC": {"tier": 2, "label": "BBC"},
    "NYT": {"tier": 2, "label": "New York Times"},
    "FOX": {"tier": 2, "label": "Fox News"},
    "ALJAZ": {"tier": 2, "label": "Al Jazeera"},
    "NPR": {"tier": 2, "label": "NPR"},
    "PBS": {"tier": 2, "label": "PBS NewsHour"},
    "MILTIMES": {"tier": 2, "label": "Military Times"},
    "STRIPES": {"tier": 2, "label": "Stars and Stripes"},
    "WSJ": {"tier": 2, "label": "Wall Street Journal"},
    "AVWEEK": {"tier": 2, "label": "Aviation Week"},
    "THENATIONAL": {"tier": 2, "label": "The National News"},
    "ABCNEWS": {"tier": 2, "label": "ABC News"},
    "NBCNEWS": {"tier": 2, "label": "NBC News"},
    "TOIISRAEL": {"tier": 2, "label": "Times of Israel"},
    "WAPO": {"tier": 2, "label": "Washington Post"},
    "WARZONE": {"tier": 3, "label": "The War Zone"},
    "CSIS": {"tier": 3, "label": "CSIS"},
    "CFR": {"tier": 3, "label": "CFR"},
    "ATLANTIC": {"tier": 3, "label": "Atlantic Council"},
    "DEFSCOOP": {"tier": 3, "label": "DefenseScoop"},
    "STIMSON": {"tier": 3, "label": "Stimson Center"},
    "IRGC_TG": {"tier": 4, "label": "IRGC-linked Telegram"},
    "PRAVDA_EN": {"tier": 4, "label": "Pravda-EN (secondary ref)"},
}

DEFAULT_SOURCE_REGISTRY = {
    "DOD": {"tier": 1, "label": "U.S. Department of Defense release"},
    "CISA": {"tier": 1, "label": "CISA cybersecurity advisory"},
    "WHITEHOUSE": {"tier": 1, "label": "White House release"},
    "BREAKDEF": {"tier": 2, "label": "Breaking Defense"},
    "DEFONE": {"tier": 3, "label": "Defense One"},
    "SOFNEWS": {"tier": 3, "label": "SOF News"},
    "TENABLE": {"tier": 3, "label": "Tenable blog"},
}


def ensure_directories() -> None:
    for path in (OUTPUT_DIR, JSON_DIR, DOCX_DIR, PDF_DIR, MD_DIR, HTML_DIR, LOG_DIR, DASHBOARD_DIR):
        path.mkdir(parents=True, exist_ok=True)


def load_shared_env(strict: bool = False) -> None:
    if load_dotenv is None:
        if strict:
            raise RuntimeError("python-dotenv is not installed. Run `bash setup.sh` first.")
        return
    if SHARED_ENV_PATH.exists():
        load_dotenv(dotenv_path=SHARED_ENV_PATH, override=False)


def configure_logging(name: str, log_path: Path | None = None, console: bool = True) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
        return logger

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    if console:
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(formatter)
        logger.addHandler(stream)

    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def parse_run_date(raw_value: str | None = None) -> date:
    if raw_value:
        return date.fromisoformat(raw_value)
    return datetime.now(timezone.utc).date()


def human_date(value: date) -> str:
    return f"{value.strftime('%B')} {value.day}, {value.year}"


def et_now() -> datetime:
    if ZoneInfo is None:
        return datetime.now(timezone.utc)
    return datetime.now(ZoneInfo("America/New_York"))


def infer_update_time_label() -> str:
    now_et = et_now()
    hour = now_et.hour
    if 5 <= hour < 12:
        bucket = "Morning ET"
    elif 12 <= hour < 17:
        bucket = "Afternoon ET"
    else:
        bucket = "Evening ET"
    return bucket


def compute_day_number(run_date: date) -> int:
    return (run_date - EVENT_START_DATE).days + 1


def compute_day_label(run_date: date) -> str:
    return f"DAY {compute_day_number(run_date)}"


def output_paths(run_date: date) -> dict[str, Path]:
    stamp = run_date.isoformat()
    return {
        "osint_json": JSON_DIR / f"osint_{stamp}.json",
        "brief_json": JSON_DIR / f"epic_fury_{stamp}.json",
        "docx": DOCX_DIR / f"epic_fury_{stamp}.docx",
        "pdf": PDF_DIR / f"epic_fury_{stamp}.pdf",
        "md": MD_DIR / f"epic_fury_{stamp}.md",
        "html": HTML_DIR / f"epic_fury_{stamp}.html",
        "qc_json": JSON_DIR / f"qc_{stamp}.json",
        "product_pdf": PDF_DIR / "threatwatch_iran_monitor_product_sheet.pdf",
    }


def manifest_paths(run_date: date) -> dict[str, str]:
    stamp = run_date.isoformat()
    return {
        "date": stamp,
        "json": f"../output/json/epic_fury_{stamp}.json",
        "html": f"../output/html/epic_fury_{stamp}.html",
        "pdf": f"../output/pdf/epic_fury_{stamp}.pdf",
        "docx": f"../output/docx/epic_fury_{stamp}.docx",
        "markdown": f"../output/md/epic_fury_{stamp}.md",
        "qc": f"../output/json/qc_{stamp}.json",
    }


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n")


def load_starter_template() -> dict[str, Any]:
    return deepcopy(read_json(BRIEF_STARTER_PATH))


def strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = unescape(text)
    return normalize_space(text)


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def strip_markdown_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def iter_string_values(node: Any) -> Iterable[str]:
    if isinstance(node, dict):
        for value in node.values():
            yield from iter_string_values(value)
    elif isinstance(node, list):
        for item in node:
            yield from iter_string_values(item)
    elif isinstance(node, str):
        yield node


def find_placeholders(node: Any) -> list[str]:
    hits: list[str] = []
    for value in iter_string_values(node):
        upper_value = value.upper()
        for token in PLACEHOLDER_PATTERNS:
            if token in upper_value:
                hits.append(value)
                break
    return hits


def title_similarity(title_a: str, title_b: str) -> float:
    tokens_a = {token for token in re.findall(r"[a-z0-9]+", title_a.lower()) if len(token) > 1}
    tokens_b = {token for token in re.findall(r"[a-z0-9]+", title_b.lower()) if len(token) > 1}
    if not tokens_a or not tokens_b:
        return 0.0
    overlap = tokens_a & tokens_b
    return len(overlap) / max(len(tokens_a), len(tokens_b))


def parse_datetime_value(value: Any) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    if hasattr(value, "tm_year"):
        return datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)

    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None

        iso_value = candidate.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(iso_value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

        fmts = (
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S GMT",
            "%B %d, %Y",
            "%b %d, %Y",
            "%Y-%m-%d %H:%M:%S %z",
            "%Y-%m-%d",
        )
        for fmt in fmts:
            try:
                parsed = datetime.strptime(candidate, fmt)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                continue

    return None


def reference_anchor(run_date: date) -> datetime:
    today_utc = datetime.now(timezone.utc).date()
    if run_date == today_utc:
        return datetime.now(timezone.utc)
    return datetime.combine(run_date, time(23, 59, 59), tzinfo=timezone.utc)


def build_source_lookup(source_registry: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    lookup = deepcopy(BUILTIN_SOURCES)
    lookup.update(deepcopy(DEFAULT_SOURCE_REGISTRY))
    if source_registry:
        lookup.update(deepcopy(source_registry))
    return lookup


def source_tier(source_id: str, source_registry: dict[str, Any] | None = None) -> int | None:
    lookup = build_source_lookup(source_registry)
    source = lookup.get(source_id)
    if not source:
        return None
    return int(source.get("tier", 0))


def source_label(source_id: str, source_registry: dict[str, Any] | None = None) -> str:
    lookup = build_source_lookup(source_registry)
    if source_id in lookup:
        return lookup[source_id].get("label", source_id)
    return source_id


def ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def file_size_map(paths: dict[str, Path]) -> dict[str, int]:
    results: dict[str, int] = {}
    for key, path in paths.items():
        if path.exists():
            results[key] = path.stat().st_size
    return results


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
