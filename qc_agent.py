#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import (
    CLASSIFICATION,
    LOG_DIR,
    build_source_lookup,
    configure_logging,
    ensure_directories,
    file_size_map,
    find_placeholders,
    human_date,
    output_paths,
    parse_run_date,
    read_json,
    source_tier,
    write_json,
)

LOGGER = configure_logging("qc_agent", LOG_DIR / "pipeline.log")
EXEC_TYPES = ["fact", "fact", "assessment", "assessment", "uncertainty"]
VALID_CONF = {"HIGH", "MED", "LOW"}
REQUIRED_CFG = {
    "productName",
    "eventTitle",
    "dayLabel",
    "date",
    "updateTime",
    "classification",
    "audience",
    "outputFile",
}


def check(name: str, passed: bool, detail: str, critical: bool) -> dict[str, Any]:
    return {"name": name, "passed": passed, "detail": detail, "critical": critical}


def collect_source_ids(brief: dict[str, Any]) -> list[str]:
    ids: list[str] = []

    def walk(node: Any):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "sources" and isinstance(value, list):
                    ids.extend([source_id for source_id in value if isinstance(source_id, str)])
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(brief)
    return ids


def high_conf_section_claims(brief: dict[str, Any]) -> int:
    count = 0
    for section in brief.get("sections", []):
        for item in section.get("items", []):
            if item.get("type") == "claim" and item.get("conf") == "HIGH":
                count += 1
    return count


def empty_text_items(brief: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for section in brief.get("sections", []):
        for item in section.get("items", []):
            item_type = item.get("type")
            if item_type not in {"h3", "claim", "callout"}:
                continue
            text = item.get("text", "")
            if isinstance(text, str) and not text.strip():
                failures.append(f"{section.get('domainTitle', 'Section')}:{item_type}")
            elif isinstance(text, list) and not " ".join(text).strip():
                failures.append(f"{section.get('domainTitle', 'Section')}:{item_type}")
    return failures


def t4_conf_violations(brief: dict[str, Any], registry: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    for section in brief.get("sections", []):
        for item in section.get("items", []):
            sources = item.get("sources", [])
            if not sources:
                continue
            tiers = [source_tier(source_id, registry) for source_id in sources]
            tiers = [tier for tier in tiers if tier is not None]
            if tiers and all(tier == 4 for tier in tiers) and item.get("conf") in {"HIGH", "MED"}:
                violations.append(section.get("domainTitle", "Unknown section"))
    return violations


def validate_qc(run_date, brief_path: Path | None = None) -> tuple[int, dict[str, Any]]:
    ensure_directories()
    paths = output_paths(run_date)
    brief = read_json(brief_path or paths["brief_json"])
    registry = build_source_lookup(brief.get("sourceRegistry", {}))
    checks: list[dict[str, Any]] = []

    cfg = brief.get("cfg", {})
    checks.append(
        check(
            "cfg fields present",
            isinstance(cfg, dict) and REQUIRED_CFG.issubset(cfg.keys()),
            "All required cfg fields must exist.",
            True,
        )
    )

    exec_summary = brief.get("execSummary", [])
    checks.append(
        check(
            "execSummary order",
            isinstance(exec_summary, list) and len(exec_summary) == 5 and [item.get("type") for item in exec_summary] == EXEC_TYPES,
            "Exec summary must contain five items in fact/fact/assessment/assessment/uncertainty order.",
            True,
        )
    )
    checks.append(
        check(
            "execSummary confidence values",
            all(item.get("conf") in VALID_CONF for item in exec_summary if item.get("type") != "uncertainty"),
            "All confidence values must be HIGH, MED, or LOW.",
            True,
        )
    )
    checks.append(
        check(
            "section count",
            isinstance(brief.get("sections"), list) and len(brief.get("sections", [])) >= 2,
            "At least two domain sections are required.",
            True,
        )
    )
    checks.append(
        check(
            "scorecard row count",
            8 <= len(brief.get("scorecard", [])) <= 12,
            "Scorecard should contain 8-12 rows.",
            False,
        )
    )
    checks.append(
        check(
            "scorecard row fields",
            all(
                all(row.get(field) for field in ("indicator", "status", "change", "watch"))
                for row in brief.get("scorecard", [])
            ),
            "Each scorecard row needs indicator, status, change, and watch.",
            True,
        )
    )
    action_groups = brief.get("actions", {})
    non_empty_action_groups = [key for key, value in action_groups.items() if isinstance(value, list) and value]
    checks.append(
        check(
            "actions groups",
            "cyber" in non_empty_action_groups and len(non_empty_action_groups) >= 2,
            "Actions must include cyber and at least one other group.",
            True,
        )
    )
    appendix = brief.get("sourcesAppendix", {})
    checks.append(
        check(
            "sources appendix populated",
            bool(appendix.get("t1") or appendix.get("t2")),
            "sourcesAppendix needs populated t1 or t2 entries.",
            True,
        )
    )

    source_ids = collect_source_ids(brief)
    unknown_ids = [source_id for source_id in source_ids if source_id not in registry]
    checks.append(
        check(
            "known source IDs",
            not unknown_ids,
            f"Unknown source IDs: {', '.join(sorted(set(unknown_ids)))}" if unknown_ids else "All sources resolve.",
            False,
        )
    )
    t4_violations = t4_conf_violations(brief, registry)
    checks.append(
        check(
            "T4 confidence discipline",
            not t4_violations,
            f"T4-only claims above LOW found in: {', '.join(sorted(set(t4_violations)))}" if t4_violations else "No T4-only confidence escalation found.",
            False,
        )
    )
    high_claims = high_conf_section_claims(brief)
    checks.append(
        check(
            "high-confidence claim count",
            high_claims >= 3,
            f"Found {high_claims} HIGH-confidence section claims.",
            False,
        )
    )

    placeholders = find_placeholders(brief)
    checks.append(
        check(
            "no placeholder text",
            not placeholders,
            f"Placeholder tokens found: {placeholders[:5]}" if placeholders else "No placeholders detected.",
            True,
        )
    )
    event_title = str(cfg.get("eventTitle", "")).upper()
    checks.append(
        check(
            "event title scope",
            "EPIC FURY" in event_title or "IRAN" in event_title,
            "Event title should include EPIC FURY or IRAN.",
            True,
        )
    )
    checks.append(
        check(
            "date matches run date",
            cfg.get("date") == human_date(run_date),
            f"Expected {human_date(run_date)}.",
            True,
        )
    )
    empty_items = empty_text_items(brief)
    checks.append(
        check(
            "no empty section text",
            not empty_items,
            f"Empty text fields: {', '.join(empty_items)}" if empty_items else "No empty section text fields.",
            True,
        )
    )

    sizes = file_size_map(paths)
    checks.append(check("DOCX exists and >10KB", sizes.get("docx", 0) > 10_240, f"Size={sizes.get('docx', 0)} bytes", True))
    checks.append(check("PDF exists and >20KB", sizes.get("pdf", 0) > 20_480, f"Size={sizes.get('pdf', 0)} bytes", True))
    checks.append(check("MD exists and >500 chars", sizes.get("md", 0) > 500, f"Size={sizes.get('md', 0)} bytes", True))
    checks.append(check("HTML exists and >2000 chars", sizes.get("html", 0) > 2_000, f"Size={sizes.get('html', 0)} bytes", True))

    critical_failures = [item for item in checks if item["critical"] and not item["passed"]]
    exit_code = 1 if critical_failures else 0
    report = {
        "run_date": run_date.isoformat(),
        "classification": CLASSIFICATION,
        "passed": exit_code == 0,
        "critical_failures": len(critical_failures),
        "checks": checks,
        "file_sizes": sizes,
    }
    write_json(paths["qc_json"], report)
    return exit_code, report


def print_report(report: dict[str, Any]) -> None:
    for item in report["checks"]:
        if item["passed"]:
            status = "PASS"
        elif item["critical"]:
            status = "FAIL"
        else:
            status = "WARN"
        print(f"[{status}] {item['name']} — {item['detail']}")


def run_qc(run_date, brief_path: Path | None = None) -> tuple[int, dict[str, Any]]:
    exit_code, report = validate_qc(run_date, brief_path=brief_path)
    print_report(report)
    return exit_code, report


def main() -> int:
    parser = argparse.ArgumentParser(description="QC audit the generated ThreatWatch brief.")
    parser.add_argument("--date", help="Run date in YYYY-MM-DD format")
    parser.add_argument("--brief", help="Optional brief JSON input path")
    args = parser.parse_args()
    run_date = parse_run_date(args.date)
    exit_code, report = run_qc(run_date, brief_path=Path(args.brief) if args.brief else None)
    LOGGER.info("QC complete. Passed=%s", report["passed"])
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
