#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import smtplib
from copy import deepcopy
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, parseaddr
from pathlib import Path

from common import (
    CLIENTS_PATH,
    JSON_DIR,
    LOG_DIR,
    SHARED_ENV_PATH,
    configure_logging,
    ensure_directories,
    file_size_map,
    human_date,
    load_shared_env,
    manifest_paths,
    output_paths,
    parse_run_date,
    read_json,
    write_json,
)
from fetch_osint import article_counts, collect_osint, save_osint
from generate_brief import generate_brief
from html_renderer import render_html
from md_exporter import export_markdown
from pdf_exporter import export_pdf
from product_sheet import generate_product_sheet
from qc_agent import run_qc

LOGGER = configure_logging("pipeline", LOG_DIR / "pipeline.log")


def manifest_entry(brief_path: Path) -> dict:
    brief = read_json(brief_path)
    date_str = brief_path.stem.replace("epic_fury_", "")
    entry = manifest_paths(datetime.fromisoformat(date_str).date())
    entry.update(
        {
            "dayLabel": brief.get("cfg", {}).get("dayLabel", ""),
            "title": brief.get("cfg", {}).get("eventTitle", ""),
            "classification": brief.get("cfg", {}).get("classification", ""),
        }
    )
    return entry


def update_manifest() -> Path:
    briefs = sorted(JSON_DIR.glob("epic_fury_*.json"))
    entries = [manifest_entry(path) for path in briefs]
    entries.sort(key=lambda item: item["date"], reverse=True)
    payload = {"briefs": entries, "updated_at": formatdate(usegmt=True)}
    manifest_path = JSON_DIR / "manifest.json"
    write_json(manifest_path, payload)
    return manifest_path


def smtp_settings() -> dict[str, str]:
    load_shared_env(strict=False)
    return {
        "host": os.getenv("SMTP_HOST", "").strip(),
        "port": os.getenv("SMTP_PORT", "").strip(),
        "user": os.getenv("SMTP_USER", "").strip(),
        "password": os.getenv("SMTP_PASS", "").strip(),
        "from": os.getenv("SMTP_FROM", "").strip(),
        "reply_to": os.getenv("SMTP_REPLY_TO", "").strip(),
        "legacy_host": os.getenv("SMTP_SERVER", "").strip(),
        "legacy_user": os.getenv("SMTP_USERNAME", "").strip(),
        "legacy_password": os.getenv("SMTP_PASSWORD", "").strip(),
        "alert_to": os.getenv("ALERT_TO_EMAIL", "").strip(),
    }


def smtp_connect(settings: dict[str, str]):
    host = settings["host"] or settings["legacy_host"] or "smtp.gmail.com"
    port = int(settings["port"] or 587)
    user = settings["user"] or settings["legacy_user"]
    password = settings["password"] or settings["legacy_password"]
    server = smtplib.SMTP(host, port)
    server.starttls()
    if user and password:
        server.login(user, password)
    return server


def send_email(message: EmailMessage, settings: dict[str, str]) -> None:
    with smtp_connect(settings) as server:
        server.send_message(message)


def delivery_log(message: str) -> None:
    path = LOG_DIR / "delivery.log"
    with path.open("a") as handle:
        handle.write(f"{datetime.utcnow().isoformat()}Z | {message}\n")


def build_delivery_message(client: dict, brief: dict, pdf_path: Path, settings: dict[str, str]) -> EmailMessage:
    summary = brief.get("execSummary", [{}])[0].get("text", "Daily ThreatWatch brief attached.")
    subject = f"[ThreatWatch AI] Operation Epic Fury — {brief['cfg']['dayLabel']} | {brief['cfg']['date']}"
    from_header = settings["from"] or f"ThreatWatch AI <{settings['user'] or settings['legacy_user']}>"
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_header
    message["To"] = client["email"]
    if settings["reply_to"]:
        message["Reply-To"] = settings["reply_to"]
    message.set_content(f"{summary}\n\nFull brief attached as PDF.")
    message.add_alternative(
        f"""
        <html>
          <body style="font-family:Georgia,serif;background:#f3f8fb;padding:20px;color:#18212B;">
            <div style="max-width:620px;margin:auto;background:white;border:1px solid #d7dee6;border-radius:16px;overflow:hidden;">
              <div style="background:#1B3A5C;color:white;padding:18px 24px;font-size:22px;font-weight:700;">ThreatWatch AI</div>
              <div style="padding:22px 24px;">
                <p style="margin:0 0 14px;line-height:1.6;">{summary}</p>
                <p style="margin:0 0 16px;line-height:1.6;">Download the attached PDF for the full brief.</p>
                <p style="margin:0;color:#5a6672;font-size:13px;">Unsubscribe placeholder</p>
              </div>
            </div>
          </body>
        </html>
        """,
        subtype="html",
    )
    message.add_attachment(pdf_path.read_bytes(), maintype="application", subtype="pdf", filename=pdf_path.name)
    return message


def deliver_brief(run_date, brief_path: Path, pdf_path: Path) -> None:
    settings = smtp_settings()
    if not settings["password"]:
        delivery_log("DELIVERY SKIPPED: SMTP_PASS not configured")
        LOGGER.info("Delivery skipped because SMTP_PASS is not configured.")
        return

    if not CLIENTS_PATH.exists():
        delivery_log("DELIVERY SKIPPED: clients.json missing")
        LOGGER.warning("clients.json is missing; delivery skipped.")
        return

    brief = read_json(brief_path)
    client_payload = read_json(CLIENTS_PATH)
    clients = [client for client in client_payload.get("clients", []) if client.get("active") and client.get("product") == "iran_monitor"]
    for client in clients:
        try:
            message = build_delivery_message(client, brief, pdf_path, settings)
            send_email(message, settings)
            delivery_log(f"DELIVERED: {client['id']} -> {client['email']}")
        except Exception as exc:
            delivery_log(f"DELIVERY FAILED: {client.get('id', 'UNKNOWN')} -> {exc}")
            LOGGER.error("Delivery failed for %s: %s", client.get("id", "UNKNOWN"), exc)


def brandon_alert_address(settings: dict[str, str]) -> str | None:
    smtp_user = settings["user"] or settings["legacy_user"]
    if smtp_user and "@" in smtp_user:
        return f"brandonwagener@{smtp_user.split('@', 1)[1]}"
    if settings["alert_to"]:
        return settings["alert_to"]
    from_addr = parseaddr(settings["from"])[1]
    if from_addr and "@" in from_addr:
        return f"brandonwagener@{from_addr.split('@', 1)[1]}"
    return None


def send_qc_failure_alert(run_date, report: dict) -> None:
    settings = smtp_settings()
    alert_to = brandon_alert_address(settings)
    password = settings["password"] or settings["legacy_password"]
    if not alert_to or not password:
        LOGGER.warning("QC failure alert skipped; SMTP details incomplete.")
        return

    failed = [item for item in report["checks"] if item["critical"] and not item["passed"]]
    message = EmailMessage()
    message["Subject"] = f"[ThreatWatch AI] QC FAILED — Operation Epic Fury | {human_date(run_date)}"
    message["From"] = settings["from"] or settings["user"] or settings["legacy_user"]
    message["To"] = alert_to
    body = "Critical QC checks failed:\n\n" + "\n".join(f"- {item['name']}: {item['detail']}" for item in failed)
    message.set_content(body)
    try:
        send_email(message, settings)
        delivery_log(f"QC ALERT SENT: {alert_to}")
    except Exception as exc:
        delivery_log(f"QC ALERT FAILED: {alert_to} -> {exc}")
        LOGGER.warning("QC failure alert could not be sent: %s", exc)


def ensure_env_placeholders() -> None:
    if not SHARED_ENV_PATH.exists():
        return
    existing = SHARED_ENV_PATH.read_text()
    required_keys = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "SMTP_FROM", "SMTP_REPLY_TO"]
    if all(f"{key}=" in existing for key in required_keys):
        return
    block = """

# ThreatWatch Iran Monitor delivery settings.
# Fill these with a Gmail account that has 2FA enabled and an App Password configured.
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=threatwatch@wagenerframeworks.com
SMTP_PASS=
SMTP_FROM=ThreatWatch AI <threatwatch@wagenerframeworks.com>
SMTP_REPLY_TO=threatwatch@wagenerframeworks.com
""".rstrip()
    SHARED_ENV_PATH.write_text(existing.rstrip() + block + "\n")


def pipeline(run_date, deliver: bool = False, dry_run: bool = False) -> int:
    ensure_directories()
    load_shared_env(strict=False)
    paths = output_paths(run_date)

    osint_payload = collect_osint(run_date)
    osint_path = save_osint(osint_payload, run_date)
    counts = article_counts(osint_payload)
    LOGGER.info("Fetched OSINT articles by tier: %s", dict(counts))
    if len(osint_payload.get("articles", [])) < 3:
        LOGGER.warning("Fewer than 3 OSINT articles fetched; continuing with caution.")

    try:
        brief_path = generate_brief(run_date, osint_path=osint_path, dry_run=dry_run)
    except Exception as exc:
        failure_report = {
            "run_date": run_date.isoformat(),
            "passed": False,
            "critical_failures": 1,
            "checks": [
                {
                    "name": "brief generation",
                    "passed": False,
                    "detail": str(exc),
                    "critical": True,
                }
            ],
            "file_sizes": file_size_map(paths),
        }
        write_json(paths["qc_json"], failure_report)
        LOGGER.error("Brief generation failed; QC failure report written to %s", paths["qc_json"])
        send_qc_failure_alert(run_date, failure_report)
        return 1

    markdown_path = export_markdown(run_date, brief_path=brief_path)
    html_path = render_html(run_date, brief_path=brief_path)
    pdf_path = export_pdf(run_date, html_path=html_path)
    product_pdf = generate_product_sheet(run_date)
    manifest_path = update_manifest()
    qc_exit, report = run_qc(run_date, brief_path=brief_path)

    if qc_exit != 0:
        LOGGER.error("QC failed. Alerting Brandon and halting delivery.")
        send_qc_failure_alert(run_date, report)
        return 1

    if deliver and not dry_run:
        deliver_brief(run_date, brief_path, pdf_path)

    sizes = file_size_map(output_paths(run_date))
    LOGGER.info(
        "Pipeline success | brief=%s | md=%s | html=%s | pdf=%s | product=%s | manifest=%s | sizes=%s",
        brief_path,
        markdown_path,
        html_path,
        pdf_path,
        product_pdf,
        manifest_path,
        json.dumps(sizes, sort_keys=True),
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the ThreatWatch Epic Fury pipeline.")
    parser.add_argument("--date", help="Run date in YYYY-MM-DD format")
    parser.add_argument("--deliver", action="store_true", help="Send PDF brief to active clients")
    parser.add_argument("--dry-run", action="store_true", help="Skip Anthropic delivery and use heuristic brief generation")
    args = parser.parse_args()
    run_date = parse_run_date(args.date)
    return pipeline(run_date, deliver=args.deliver, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
