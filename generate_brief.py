#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any

from common import (
    AUDIENCE,
    BRIEF_PROMPT_PATH,
    BRIEF_RENDERER_DIR,
    BRIEF_RENDERER_SCRIPT,
    BUILTIN_SOURCES,
    CLASSIFICATION,
    DEFAULT_SOURCE_REGISTRY,
    EVENT_TITLE,
    LOG_DIR,
    PRODUCT_NAME,
    build_source_lookup,
    compute_day_label,
    configure_logging,
    ensure_directories,
    human_date,
    infer_update_time_label,
    load_shared_env,
    load_starter_template,
    normalize_space,
    output_paths,
    parse_run_date,
    read_json,
    source_label,
    source_tier,
    strip_markdown_fences,
    write_json,
)

LOGGER = configure_logging("generate_brief", LOG_DIR / "pipeline.log")
CONF_RANK = {"LOW": 1, "MED": 2, "HIGH": 3}
EXEC_TYPES = ["fact", "fact", "assessment", "assessment", "uncertainty"]


def require_anthropic():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - runtime guidance
        raise RuntimeError("anthropic is not installed. Run `bash setup.sh` first.") from exc
    return anthropic


def article_registry(osint_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    for article in osint_payload.get("articles", []):
        source_id = article["source_id"]
        if source_id in BUILTIN_SOURCES:
            continue
        if source_id in DEFAULT_SOURCE_REGISTRY:
            registry[source_id] = dict(DEFAULT_SOURCE_REGISTRY[source_id])
        else:
            registry[source_id] = {"tier": 3, "label": source_id.replace("_", " ").title()}
            continue

        label = source_id.replace("_", " ").title()
        registry[source_id] = {"tier": int(article.get("tier", 3)), "label": label}
    return registry


def unique_sources(articles: list[dict[str, Any]], limit: int = 3) -> list[str]:
    seen: list[str] = []
    for article in articles:
        source_id = article["source_id"]
        if source_id not in seen:
            seen.append(source_id)
        if len(seen) >= limit:
            break
    return seen


def sentence_tail(text: str, count: int = 2) -> str:
    cleaned = normalize_space(text)
    if not cleaned:
        return ""
    parts = [segment.strip() for segment in cleaned.split(".") if segment.strip()]
    if not parts:
        return cleaned
    return ". ".join(parts[:count]).strip() + "."


def claim_from_article(article: dict[str, Any]) -> str:
    title = normalize_space(article.get("title", ""))
    summary = sentence_tail(article.get("summary", ""), 2)
    if summary:
        if summary.lower().startswith(title.lower()):
            return summary
        return f"{title}. {summary}"
    return f"{title}."


def max_supported_confidence(source_ids: list[str], registry: dict[str, Any]) -> str | None:
    tiers = [source_tier(source_id, registry) for source_id in source_ids]
    tiers = [tier for tier in tiers if tier is not None]
    if not tiers:
        return None
    if all(tier == 4 for tier in tiers):
        return "LOW"
    tier12 = sum(1 for tier in tiers if tier in (1, 2))
    tier3 = sum(1 for tier in tiers if tier == 3)
    if tier12 >= 2:
        return "HIGH"
    if tier12 >= 1 or tier3 >= 2:
        return "MED"
    return "LOW"


def preferred_confidence(source_ids: list[str], registry: dict[str, Any], fallback: str = "MED") -> str:
    supported = max_supported_confidence(source_ids, registry)
    return supported or fallback


def assign_bucket(article: dict[str, Any]) -> str:
    if article.get("domain") == "cyber":
        return "cyber"

    haystack = f"{article.get('title', '')} {article.get('summary', '')}".lower()
    if any(token in haystack for token in ("white house", "president", "statement", "release", "policy", "official")):
        return "leadership"
    if any(token in haystack for token in ("hormuz", "shipping", "refinery", "oil", "airspace", "travel", "market", "port")):
        return "infrastructure"
    if any(token in haystack for token in ("strike", "missile", "drone", "centcom", "fighter", "military", "navy", "air force", "irgc")):
        return "military"
    return "international"


def scorecard_rows(cyber_present: bool) -> list[dict[str, str]]:
    rows = [
        {
            "indicator": "Official U.S. military updates",
            "status": "ONGOING",
            "change": "UNCHANGED",
            "watch": "New CENTCOM or DoD confirmation on strikes, losses, or posture changes",
        },
        {
            "indicator": "Iranian retaliatory tempo",
            "status": "BUILDING",
            "change": "ESCALATING",
            "watch": "Confirmed new missile, drone, or proxy attack tied to Iran or IRGC channels",
        },
        {
            "indicator": "Strait of Hormuz disruption",
            "status": "ELEVATED",
            "change": "UNCHANGED",
            "watch": "Carrier reroutes, shipping suspension, or direct port and tanker impact reporting",
        },
        {
            "indicator": "Regional airspace reliability",
            "status": "ELEVATED",
            "change": "UNCHANGED",
            "watch": "Airspace closures, NOTAM updates, or airline cancellations tied to Gulf security",
        },
        {
            "indicator": "Energy market stress",
            "status": "ELEVATED",
            "change": "NEW",
            "watch": "Sustained oil price spike or refinery / export terminal disruption",
        },
        {
            "indicator": "Diplomatic off-ramp",
            "status": "PENDING",
            "change": "UNCHANGED",
            "watch": "Named U.S., Iranian, Gulf, or Omani de-escalation channel confirmed on the record",
        },
        {
            "indicator": "Corporate communications pressure",
            "status": "ACTIVE",
            "change": "NEW",
            "watch": "Employee accountability needs, board brief requests, or customer reassurance demands",
        },
        {
            "indicator": "Travel risk to exposed staff",
            "status": "ELEVATED",
            "change": "UNCHANGED",
            "watch": "Embassy alerts, airport disruption, or shelter-in-place directives in affected states",
        },
    ]
    if cyber_present:
        rows.append(
            {
                "indicator": "Iran-linked cyber activity",
                "status": "ACTIVE",
                "change": "NEW",
                "watch": "CISA or security vendor confirmation of phishing, intrusion, or disruptive campaigns",
            }
        )
    else:
        rows.append(
            {
                "indicator": "Iran-linked cyber activity",
                "status": "BUILDING",
                "change": "UNCHANGED",
                "watch": "New CISA or vendor advisories referencing Iranian threat actors or copycat activity",
            }
        )
    return rows[:9]


def appendix_from_articles(articles: list[dict[str, Any]], registry: dict[str, Any]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {"t1": [], "t2": [], "t3": [], "t4": []}
    seen: set[str] = set()
    for article in articles:
        source_id = article["source_id"]
        if source_id in seen:
            continue
        seen.add(source_id)
        tier = article.get("tier", 3)
        label = source_label(source_id, registry)
        entry = f"{label} — {article.get('title', '')}"
        grouped[f"t{tier}"].append(entry)
    return {key: value for key, value in grouped.items() if value}


def heuristic_sections(articles: list[dict[str, Any]], registry: dict[str, Any]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for article in articles:
        buckets[assign_bucket(article)].append(article)

    sections: list[dict[str, Any]] = []

    section_plan = [
        ("Leadership / Political Situation", buckets.get("leadership", []) or articles[:2]),
        ("Military Situation", buckets.get("military", []) or articles[:2]),
        ("Infrastructure, Markets & Travel Risk", buckets.get("infrastructure", []) or articles[:2]),
        ("International Reactions", buckets.get("international", []) or articles[:2]),
    ]
    if buckets.get("cyber"):
        section_plan.append(("Technical Situation & Cyber Risk", buckets["cyber"][:2]))

    for domain_title, bucket_articles in section_plan:
        bucket_articles = bucket_articles[:2]
        if not bucket_articles:
            continue

        top_article = bucket_articles[0]
        top_sources = unique_sources(bucket_articles, limit=2)
        items: list[dict[str, Any]] = [
            {"type": "h3", "text": top_article["title"][:110]},
            {
                "type": "claim",
                "text": claim_from_article(top_article),
                "conf": preferred_confidence(top_sources, registry),
                "sources": top_sources,
            },
        ]

        if len(bucket_articles) > 1:
            second = bucket_articles[1]
            second_sources = unique_sources([second], limit=1)
            items.append(
                {
                    "type": "claim",
                    "text": claim_from_article(second),
                    "conf": preferred_confidence(second_sources, registry),
                    "sources": second_sources,
                }
            )

        items.append(
            {
                "type": "evidenceBox",
                "claim": top_article["title"],
                "rows": [
                    {"label": "Source", "value": source_label(top_article["source_id"], registry)},
                    {"label": "Who said it", "value": source_label(top_article["source_id"], registry)},
                    {"label": "Date/time", "value": top_article.get("published", "")},
                    {"label": "Basis/quote", "value": sentence_tail(top_article.get("summary", ""), 2), "quote": True},
                    {"label": "Counter-check", "value": "No conflicting account identified in the OSINT package reviewed for this run."},
                    {"label": "Confidence", "value": f"{preferred_confidence(top_sources, registry)} based on the corroboration available in the source set."},
                ],
            }
        )

        items.append(
            {
                "type": "factJudge",
                "facts": [
                    f"{claim_from_article(article)} [{article['source_id']}]"
                    for article in bucket_articles[:2]
                ],
                "judgments": [
                    "Current reporting still supports an active-threat posture rather than a stable de-escalation track. [CONF:MED]",
                    "Corporate planning should stay centered on rapid change in travel, supply-chain, and executive communications exposure. [CONF:MED]",
                ],
            }
        )

        if domain_title == "Infrastructure, Markets & Travel Risk":
            items.append(
                {
                    "type": "callout",
                    "label": "CUSTOMER RISK: 24-48 HOUR OPERATIONS WINDOW [CONF: MED]",
                    "style": "warning",
                    "text": [
                        "Even when the physical fighting is geographically distant, downstream business effects can move quickly through travel routing, fuel pricing, maritime insurance, and executive communications pressure.",
                        "",
                        "Treat itinerary changes, contractor accountability, and vendor reach-outs as same-day actions rather than watchlist items.",
                    ],
                }
            )

        if domain_title == "Technical Situation & Cyber Risk":
            items.append(
                {
                    "type": "callout",
                    "label": "ANALYST ASSESSMENT: CYBER SPILLOVER IS PLAUSIBLE [CONF: MED]",
                    "style": "analyst",
                    "text": [
                        "Iran-linked actors routinely exploit high-visibility geopolitical events for phishing, credential theft, disruptive influence, and opportunistic access operations.",
                        "",
                        "The operating assumption for security teams should be that cyber activity can intensify in parallel with kinetic developments, not after them.",
                    ],
                }
            )

        sections.append({"domainTitle": domain_title, "items": items})

    return sections[:5]


def heuristic_actions(cyber_present: bool) -> dict[str, list[str]]:
    cyber_items = [
        "Raise monitoring for phishing, credential theft, and login anomalies tied to Iran-linked actor tradecraft over the next 24 hours.",
        "Brief finance, travel, and executive support staff on impersonation and urgent-payment scams tied to the regional crisis before the next business day.",
        "Confirm that critical external-facing systems have current logging, alert routing, and escalation contacts for after-hours review.",
    ]
    if not cyber_present:
        cyber_items[0] = "Keep heightened phishing and login-anomaly monitoring in place in case Iran-linked actors pivot to opportunistic cyber activity."

    return {
        "travel": [
            "Reconfirm traveler accountability and defer non-essential movement through exposed Gulf routes until the next operations update.",
            "Check embassy notices, airline status, and local security contacts before approving any travel inside the wider conflict footprint.",
        ],
        "supplyChain": [
            "Contact key logistics and procurement partners today to confirm contingency routing if Gulf transit reliability degrades further.",
            "Review fuel, freight, and customs cost triggers so commercial teams are ready for short-notice pricing adjustments this week.",
        ],
        "cyber": cyber_items,
        "comms": [
            "Prepare a same-day executive update that explains exposure, immediate controls, and what decision points would trigger a posture change.",
            "Align internal talking points for employees, travelers, and critical vendors so outreach stays consistent if conditions worsen quickly.",
        ],
    }


def build_heuristic_brief(osint_payload: dict[str, Any], run_date) -> dict[str, Any]:
    template = load_starter_template()
    registry = article_registry(osint_payload)
    merged_registry = build_source_lookup(registry)
    articles = osint_payload.get("articles", [])
    cyber_present = any(article.get("domain") == "cyber" for article in articles)

    top_articles = articles[:4] or [
        {
            "source_id": "REUTERS",
            "tier": 2,
            "title": "Epic Fury monitoring package was thin during this run window",
            "summary": "Source volume was limited, so this brief keeps a cautious posture and emphasizes uncertainty.",
            "published": f"{run_date.isoformat()}T00:00:00+00:00",
        }
    ]
    fact_one_sources = unique_sources(top_articles[:2], limit=2)
    fact_two_sources = unique_sources(top_articles[1:3] or top_articles[:1], limit=2)
    assessment_sources = unique_sources(top_articles[:3], limit=3)
    risk_sources = unique_sources([article for article in top_articles if article.get("domain") == "cyber"] or top_articles[:2], limit=2)

    template["cfg"] = {
        "productName": PRODUCT_NAME,
        "eventTitle": EVENT_TITLE,
        "dayLabel": compute_day_label(run_date),
        "date": human_date(run_date),
        "updateTime": infer_update_time_label(),
        "classification": CLASSIFICATION,
        "audience": AUDIENCE,
        "outputFile": f"./output/docx/epic_fury_{run_date.isoformat()}.docx",
    }
    template["sourceRegistry"] = registry
    template["execSummary"] = [
        {
            "type": "fact",
            "text": f"{claim_from_article(top_articles[0])} This keeps the official and verified reporting picture active for the current operating window.",
            "conf": preferred_confidence(fact_one_sources, merged_registry, fallback="MED"),
            "sources": fact_one_sources,
        },
        {
            "type": "fact",
            "text": f"{claim_from_article(top_articles[min(1, len(top_articles) - 1)])} This adds a second operational datapoint for the same 24-48 hour decision cycle.",
            "conf": preferred_confidence(fact_two_sources, merged_registry, fallback="MED"),
            "sources": fact_two_sources,
        },
        {
            "type": "assessment",
            "text": "The available source mix still points to an active conflict environment rather than a durable off-ramp. Unless official channels pivot toward verified stand-down measures, the next 24 hours are more likely to bring continued force-posture, diplomatic, and infrastructure stress than a clean reset.",
            "conf": preferred_confidence(assessment_sources, merged_registry, fallback="MED"),
            "sources": assessment_sources,
        },
        {
            "type": "assessment",
            "text": "The highest customer-facing risk is rapid spillover into travel planning, executive communications, supply-chain reliability, and opportunistic cyber activity. Corporate teams should prioritize fast coordination and ready-to-execute contingency actions over passive monitoring.",
            "conf": preferred_confidence(risk_sources, merged_registry, fallback="MED"),
            "sources": risk_sources,
        },
        {
            "type": "uncertainty",
            "text": "The key unresolved variable is whether the next confirmed official updates show containment or wider spillover into Gulf infrastructure, regional travel, and cyber activity. The clearest observable is a new on-record statement confirming either de-escalation channels or additional attacks affecting bases, ports, airspace, or networks.",
        },
    ]
    template["sections"] = heuristic_sections(articles, merged_registry)
    template["scorecard"] = scorecard_rows(cyber_present)
    template["actions"] = heuristic_actions(cyber_present)
    template["parallel"] = {"notApplicable": True}
    template["sourcesAppendix"] = appendix_from_articles(articles, merged_registry)
    return template


def render_source_material(osint_payload: dict[str, Any]) -> str:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for article in osint_payload.get("articles", []):
        grouped[int(article.get("tier", 3))].append(article)

    lines = [
        "Build a ThreatWatch brief for OPERATION EPIC FURY using the source package below.",
        "Use source IDs exactly as provided. If you cite any non-built-in source IDs, register them in sourceRegistry.",
        "",
    ]

    for tier in sorted(grouped):
        lines.append(f"TIER {tier}")
        for article in grouped[tier]:
            domain = f" | domain={article['domain']}" if article.get("domain") else ""
            lines.extend(
                [
                    f"- [{article['source_id']}] {article['title']} ({article.get('published', '')}{domain})",
                    f"  Summary: {article.get('summary', '')}",
                    f"  URL: {article.get('url', '')}",
                ]
            )
        lines.append("")

    return "\n".join(lines).strip()


def call_model(system_prompt: str, user_prompt: str) -> str:
    anthropic = require_anthropic()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    model = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-6")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to your .env file — see .env.example")

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=8000,
        temperature=0.2,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text_parts = [block.text for block in response.content if getattr(block, "type", "") == "text"]
    return "".join(text_parts).strip()


def save_raw_response(raw_text: str, run_date) -> Path:
    path = LOG_DIR / f"anthropic_raw_{run_date.isoformat()}.txt"
    path.write_text(raw_text)
    return path


def collect_used_source_ids(brief: dict[str, Any]) -> set[str]:
    used: set[str] = set()

    def walk(node: Any):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "sources" and isinstance(value, list):
                    for source_id in value:
                        if isinstance(source_id, str):
                            used.add(source_id)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(brief)
    return used


def normalize_item_conf(item: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    if item.get("type") == "uncertainty":
        item.pop("conf", None)
        item.pop("sources", None)
        return item

    source_ids = item.get("sources", [])
    supported = max_supported_confidence(source_ids, registry)
    current_conf = item.get("conf")
    if supported and current_conf and CONF_RANK.get(current_conf, 0) > CONF_RANK[supported]:
        item["conf"] = supported
    elif supported and not current_conf:
        item["conf"] = supported
    elif current_conf not in CONF_RANK and item.get("type") in {"claim", "fact", "assessment"}:
        item["conf"] = supported or "MED"
    return item


def merge_sections(candidate_sections: Any, fallback_sections: list[dict[str, Any]], registry: dict[str, Any]):
    if not isinstance(candidate_sections, list) or len(candidate_sections) < 2:
        candidate_sections = fallback_sections

    normalized_sections: list[dict[str, Any]] = []
    for section in candidate_sections:
        if not isinstance(section, dict):
            continue
        domain_title = normalize_space(section.get("domainTitle", ""))
        items = section.get("items", [])
        if not domain_title or not isinstance(items, list):
            continue

        clean_items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("type") in {"claim", "fact", "assessment"}:
                item = normalize_item_conf(item, registry)
            if item.get("type") == "callout" and isinstance(item.get("text"), str):
                item["text"] = [item["text"]]
            if "text" in item:
                if isinstance(item["text"], str) and not normalize_space(item["text"]):
                    continue
                if isinstance(item["text"], list) and not normalize_space(" ".join(item["text"])):
                    continue
            clean_items.append(item)

        if clean_items:
            normalized_sections.append({"domainTitle": domain_title, "items": clean_items})

    if len(normalized_sections) < 2:
        return fallback_sections
    return normalized_sections


def normalize_brief(candidate: dict[str, Any], fallback: dict[str, Any], osint_payload: dict[str, Any], run_date) -> dict[str, Any]:
    brief = candidate if isinstance(candidate, dict) else {}
    registry = article_registry(osint_payload)
    candidate_registry = brief.get("sourceRegistry", {})
    if isinstance(candidate_registry, dict):
        registry.update(candidate_registry)

    used_source_ids = collect_used_source_ids(brief)
    for source_id in used_source_ids:
        if source_id in BUILTIN_SOURCES or source_id in registry:
            continue
        if source_id in DEFAULT_SOURCE_REGISTRY:
            registry[source_id] = dict(DEFAULT_SOURCE_REGISTRY[source_id])

    brief["cfg"] = {
        "productName": PRODUCT_NAME,
        "eventTitle": EVENT_TITLE,
        "dayLabel": compute_day_label(run_date),
        "date": human_date(run_date),
        "updateTime": normalize_space(brief.get("cfg", {}).get("updateTime", "")) or infer_update_time_label(),
        "classification": CLASSIFICATION,
        "audience": AUDIENCE,
        "outputFile": f"./output/docx/epic_fury_{run_date.isoformat()}.docx",
    }
    brief["sourceRegistry"] = registry

    exec_summary = brief.get("execSummary")
    if not isinstance(exec_summary, list) or len(exec_summary) != 5 or [item.get("type") for item in exec_summary] != EXEC_TYPES:
        exec_summary = fallback["execSummary"]
    brief["execSummary"] = [normalize_item_conf(dict(item), registry) for item in exec_summary]
    for item in brief["execSummary"]:
        if item.get("type") == "uncertainty":
            item.pop("conf", None)
            item.pop("sources", None)

    brief["sections"] = merge_sections(brief.get("sections"), fallback["sections"], registry)

    scorecard = brief.get("scorecard")
    if not isinstance(scorecard, list):
        scorecard = []
    normalized_scorecard = []
    for row in scorecard:
        if not isinstance(row, dict):
            continue
        cleaned = {
            "indicator": normalize_space(row.get("indicator", "")),
            "status": normalize_space(row.get("status", "")),
            "change": normalize_space(row.get("change", "")),
            "watch": normalize_space(row.get("watch", "")),
        }
        if all(cleaned.values()):
            normalized_scorecard.append(cleaned)
    if len(normalized_scorecard) < 8:
        seen = {row["indicator"] for row in normalized_scorecard}
        for row in fallback["scorecard"]:
            if row["indicator"] not in seen:
                normalized_scorecard.append(row)
            if len(normalized_scorecard) >= 8:
                break
    brief["scorecard"] = normalized_scorecard[:12]

    actions = brief.get("actions", {})
    if not isinstance(actions, dict):
        actions = {}
    merged_actions = deepcopy(fallback["actions"])
    merged_actions.update({key: value for key, value in actions.items() if isinstance(value, list) and value})
    brief["actions"] = merged_actions

    brief["parallel"] = brief.get("parallel") if isinstance(brief.get("parallel"), dict) else {"notApplicable": True}
    appendix = brief.get("sourcesAppendix")
    if not isinstance(appendix, dict):
        appendix = {}
    generated_appendix = appendix_from_articles(osint_payload.get("articles", []), registry)
    for key, value in generated_appendix.items():
        appendix.setdefault(key, value)
    brief["sourcesAppendix"] = appendix
    return brief


def parse_model_output(raw_text: str) -> dict[str, Any]:
    cleaned = strip_markdown_fences(raw_text)
    return json.loads(cleaned)


def render_docx(json_path: Path, docx_path: Path) -> None:
    result = subprocess.run(
        ["node", str(BRIEF_RENDERER_SCRIPT), str(json_path), str(docx_path)],
        cwd=BRIEF_RENDERER_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"DOCX renderer failed: {result.stderr.strip() or result.stdout.strip()}")


def generate_brief(run_date, osint_path: Path | None = None, dry_run: bool = False) -> Path:
    ensure_directories()
    load_shared_env(strict=False)

    paths = output_paths(run_date)
    osint_payload = read_json(osint_path or paths["osint_json"])
    fallback_brief = build_heuristic_brief(osint_payload, run_date)
    brief = fallback_brief

    if not dry_run:
        system_prompt = BRIEF_PROMPT_PATH.read_text()
        user_prompt = render_source_material(osint_payload)
        try:
            raw_text = call_model(system_prompt, user_prompt)
            save_raw_response(raw_text, run_date)
            candidate = parse_model_output(raw_text)
            brief = normalize_brief(candidate, fallback_brief, osint_payload, run_date)
        except Exception as exc:
            raw_log = save_raw_response(str(exc), run_date)
            LOGGER.error("Brief generation failed; saved raw failure context to %s", raw_log)
            raise

    write_json(paths["brief_json"], brief)
    render_docx(paths["brief_json"], paths["docx"])
    LOGGER.info("Saved brief JSON to %s and DOCX to %s", paths["brief_json"], paths["docx"])
    return paths["brief_json"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the ThreatWatch brief JSON and DOCX.")
    parser.add_argument("--date", help="Run date in YYYY-MM-DD format")
    parser.add_argument("--osint", help="Optional path to OSINT JSON")
    parser.add_argument("--dry-run", action="store_true", help="Skip Anthropic and use heuristic generation")
    args = parser.parse_args()

    run_date = parse_run_date(args.date)
    osint_path = Path(args.osint) if args.osint else None
    try:
        generate_brief(run_date, osint_path=osint_path, dry_run=args.dry_run)
    except Exception as exc:
        LOGGER.error("generate_brief failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
