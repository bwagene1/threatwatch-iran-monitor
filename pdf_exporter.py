#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

from common import ensure_directories, output_paths, parse_run_date


def require_weasyprint():
    try:
        from weasyprint import HTML
    except ImportError as exc:  # pragma: no cover - runtime guidance
        raise RuntimeError("weasyprint is not installed. Run `bash setup.sh` first.") from exc
    return HTML


def print_friendly_html(source_html: Path) -> str:
    html_text = source_html.read_text()
    body_match = re.search(r"<body[^>]*>(.*)</body>", html_text, flags=re.IGNORECASE | re.DOTALL)
    body = body_match.group(1) if body_match else html_text
    body = re.sub(r"<div class=\"hero-links\">.*?</div>", "", body, flags=re.DOTALL)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <style>
    @page {{
      size: A4;
      margin: 1in;
      @bottom-center {{
        content: "ThreatWatch AI | " counter(page);
        color: #555;
        font-size: 10px;
      }}
    }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: #18212B;
      background: white;
      font-size: 11pt;
      line-height: 1.45;
    }}
    .page {{
      max-width: none;
      padding: 0;
    }}
    .cover {{
      background: #1B3A5C;
      color: white;
      padding: 22px;
      border-radius: 12px;
      margin-bottom: 18px;
    }}
    .summary-grid,
    .actions-grid,
    .fact-judge {{
      display: block;
    }}
    .summary-card,
    .action-col,
    .brief-section,
    .scorecard-wrap,
    .fact-judge > div,
    .claim-card,
    .evidence-box {{
      border: 1px solid #d7dee6;
      border-radius: 10px;
      padding: 14px;
      margin-bottom: 12px;
      box-shadow: none;
      background: white;
    }}
    .section-head {{
      background: #17627A;
      color: white;
      font-weight: 700;
      padding: 10px 12px;
      border-radius: 10px 10px 0 0;
      margin: -14px -14px 12px;
    }}
    .source-row,
    .cover-meta {{
      display: block;
      margin-top: 8px;
    }}
    .source-tag,
    .status-badge,
    .conf-badge {{
      display: inline-block;
      margin: 3px 6px 0 0;
      padding: 3px 8px;
      border-radius: 999px;
      border: 1px solid #d7dee6;
      font-size: 9pt;
    }}
    .callout {{
      border-left: 4px solid #2E75B6;
      padding: 12px;
      margin-bottom: 12px;
    }}
    .callout.warning {{ border-left-color: #C55A11; background: #FCE4D6; }}
    .callout.alert {{ border-left-color: #C00000; background: #FADADD; }}
    .callout.t4 {{ border-left-color: #7F4F00; background: #FFF2CC; }}
    .callout.analyst,
    .callout.info {{ background: #D5E8F0; }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    th, td {{
      border-top: 1px solid #d7dee6;
      padding: 8px 10px;
      text-align: left;
      vertical-align: top;
    }}
    h2, h3, h4 {{
      color: #1B3A5C;
      break-after: avoid;
    }}
    p, li {{
      orphans: 2;
      widows: 2;
    }}
    ul {{
      margin: 0;
      padding-left: 18px;
    }}
    a {{
      color: #2E75B6;
      text-decoration: none;
    }}
    footer {{
      margin-top: 18px;
      font-size: 9pt;
      color: #555;
      text-align: center;
    }}
  </style>
</head>
<body>{body}</body>
</html>"""


def export_pdf(run_date, html_path: Path | None = None, pdf_path: Path | None = None) -> Path:
    ensure_directories()
    paths = output_paths(run_date)
    source_html = html_path or paths["html"]
    target_pdf = pdf_path or paths["pdf"]
    HTML = require_weasyprint()
    HTML(string=print_friendly_html(source_html), base_url=str(source_html.parent)).write_pdf(str(target_pdf))
    return target_pdf


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the brief HTML to PDF.")
    parser.add_argument("--date", help="Run date in YYYY-MM-DD format")
    parser.add_argument("--html", help="Optional HTML input path")
    parser.add_argument("--pdf", help="Optional PDF output path")
    args = parser.parse_args()
    run_date = parse_run_date(args.date)
    export_pdf(
        run_date,
        html_path=Path(args.html) if args.html else None,
        pdf_path=Path(args.pdf) if args.pdf else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
