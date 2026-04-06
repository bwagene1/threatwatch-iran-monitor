#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import ensure_directories, output_paths, parse_run_date, read_json


def source_suffix(item: dict[str, Any]) -> str:
    sources = item.get("sources", [])
    conf = item.get("conf")
    parts = []
    if conf:
        parts.append(f"CONF:{conf}")
    if sources:
        parts.append("SOURCES:" + ", ".join(sources))
    return f" ({' | '.join(parts)})" if parts else ""


def render_fact_judge(item: dict[str, Any]) -> str:
    lines = [
        "| Confirmed Facts | Analyst Judgments |",
        "| --- | --- |",
    ]
    facts = item.get("facts", []) or [""]
    judgments = item.get("judgments", []) or [""]
    length = max(len(facts), len(judgments))
    for idx in range(length):
        left = facts[idx] if idx < len(facts) else ""
        right = judgments[idx] if idx < len(judgments) else ""
        lines.append(f"| {left} | {right} |")
    return "\n".join(lines)


def render_evidence_box(item: dict[str, Any]) -> str:
    lines = [
        f"**Evidence Box:** {item.get('claim', '')}",
        "",
        "| Label | Value |",
        "| --- | --- |",
    ]
    for row in item.get("rows", []):
        lines.append(f"| {row.get('label', '')} | {row.get('value', '')} |")
    return "\n".join(lines)


def render_section(section: dict[str, Any]) -> str:
    lines = [f"## {section.get('domainTitle', '')}", ""]
    for item in section.get("items", []):
        item_type = item.get("type")
        if item_type == "h3":
            lines.append(f"### {item.get('text', '')}")
        elif item_type == "claim":
            lines.append(f"- {item.get('text', '')}{source_suffix(item)}")
        elif item_type == "callout":
            lines.append(f"> **{item.get('label', '')}**")
            for paragraph in item.get("text", []):
                if paragraph:
                    lines.append(f"> {paragraph}")
                else:
                    lines.append(">")
        elif item_type == "factJudge":
            lines.append(render_fact_judge(item))
        elif item_type == "evidenceBox":
            lines.append(render_evidence_box(item))
        lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def export_markdown(run_date, brief_path: Path | None = None) -> Path:
    ensure_directories()
    paths = output_paths(run_date)
    brief = read_json(brief_path or paths["brief_json"])

    lines = [
        f"# ThreatWatch AI — {brief['cfg']['eventTitle']}",
        f"**{brief['cfg']['dayLabel']} | {brief['cfg']['date']} | {brief['cfg']['updateTime']}**",
        f"*{brief['cfg']['classification']}*",
        "",
        "---",
        "",
        "## Executive Summary",
    ]

    label_map = {"fact": "FACT", "assessment": "ASSESSMENT", "uncertainty": "UNCERTAINTY"}
    for item in brief.get("execSummary", []):
        conf = f" [CONF:{item['conf']}]" if item.get("conf") else ""
        lines.append(f"- **{label_map.get(item.get('type'), 'NOTE')}** {item.get('text', '')}{conf}")

    lines.extend(["", "---", ""])

    for section in brief.get("sections", []):
        lines.append(render_section(section))

    lines.extend(
        [
            "## Scorecard",
            "| Indicator | Status | Change | Watch |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in brief.get("scorecard", []):
        lines.append(
            f"| {row.get('indicator', '')} | {row.get('status', '')} | {row.get('change', '')} | {row.get('watch', '')} |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## Recommended Actions",
            "**Travel:**",
        ]
    )
    for item in brief.get("actions", {}).get("travel", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("**Supply Chain:**")
    for item in brief.get("actions", {}).get("supplyChain", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("**Cyber:**")
    for item in brief.get("actions", {}).get("cyber", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("**Comms:**")
    for item in brief.get("actions", {}).get("comms", []):
        lines.append(f"- {item}")

    lines.extend(["", "---", "", "## Sources"])
    appendix = brief.get("sourcesAppendix", {})
    for tier in ("t1", "t2", "t3", "t4"):
        entries = appendix.get(tier)
        if not entries:
            continue
        lines.append(f"**{tier.upper()}:**")
        for entry in entries:
            lines.append(f"- {entry}")
        lines.append("")

    lines.extend(
        [
            "---",
            "*ThreatWatch AI | Wagener Framework LLC | Open-source intelligence only | Not for redistribution*",
            "",
        ]
    )

    paths["md"].write_text("\n".join(lines))
    return paths["md"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the brief to Markdown.")
    parser.add_argument("--date", help="Run date in YYYY-MM-DD format")
    parser.add_argument("--brief", help="Optional path to brief JSON")
    args = parser.parse_args()
    run_date = parse_run_date(args.date)
    export_markdown(run_date, Path(args.brief) if args.brief else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
