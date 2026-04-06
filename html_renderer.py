#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
from pathlib import Path
from typing import Any

from common import ensure_directories, output_paths, parse_run_date, read_json

COLORS = {
    "dark_blue": "#1B3A5C",
    "teal": "#17627A",
    "orange": "#C55A11",
    "orange_bg": "#FCE4D6",
    "red": "#C00000",
    "red_bg": "#FADADD",
    "blue": "#2E75B6",
    "blue_bg": "#D5E8F0",
    "amber": "#7F4F00",
    "amber_bg": "#FFF2CC",
    "purple": "#5C3A7A",
    "purple_bg": "#EDE4F5",
    "gray_bg": "#F6F7F9",
    "ink": "#18212B",
}


def esc(value: Any) -> str:
    return html.escape(str(value or ""))


def render_source_tags(sources: list[str]) -> str:
    return "".join(f'<span class="source-tag">{esc(source)}</span>' for source in sources or [])


def render_exec_summary(items: list[dict[str, Any]]) -> str:
    class_map = {"fact": "fact", "assessment": "assessment", "uncertainty": "uncertainty"}
    label_map = {"fact": "FACT", "assessment": "ASSESSMENT", "uncertainty": "UNCERTAINTY"}
    cards = []
    for item in items:
        conf = f'<span class="conf-badge">{esc(item.get("conf", ""))}</span>' if item.get("conf") else ""
        cards.append(
            f"""
            <article class="summary-card {class_map.get(item.get('type'), 'fact')}">
              <div class="summary-card-head">
                <span class="summary-type">{label_map.get(item.get('type'), 'NOTE')}</span>
                {conf}
              </div>
              <p>{esc(item.get('text', ''))}</p>
              <div class="source-row">{render_source_tags(item.get('sources', []))}</div>
            </article>
            """
        )
    return "\n".join(cards)


def render_callout(item: dict[str, Any]) -> str:
    paragraphs = "".join(f"<p>{esc(paragraph)}</p>" for paragraph in item.get("text", []) if paragraph)
    return f"""
    <aside class="callout {esc(item.get('style', 'analyst'))}">
      <div class="callout-label">{esc(item.get('label', ''))}</div>
      {paragraphs}
    </aside>
    """


def render_fact_judge(item: dict[str, Any]) -> str:
    facts = "".join(f"<li>{esc(row)}</li>" for row in item.get("facts", []))
    judgments = "".join(f"<li>{esc(row)}</li>" for row in item.get("judgments", []))
    return f"""
    <div class="fact-judge">
      <div>
        <h4>Confirmed Facts</h4>
        <ul>{facts}</ul>
      </div>
      <div>
        <h4>Analyst Judgments</h4>
        <ul>{judgments}</ul>
      </div>
    </div>
    """


def render_evidence_box(item: dict[str, Any]) -> str:
    rows = "".join(
        f"<tr><th>{esc(row.get('label', ''))}</th><td>{esc(row.get('value', ''))}</td></tr>"
        for row in item.get("rows", [])
    )
    return f"""
    <div class="evidence-box">
      <div class="evidence-title">{esc(item.get('claim', ''))}</div>
      <table>{rows}</table>
    </div>
    """


def render_section_item(item: dict[str, Any]) -> str:
    item_type = item.get("type")
    if item_type == "h3":
        return f"<h3>{esc(item.get('text', ''))}</h3>"
    if item_type == "claim":
        conf = f'<span class="conf-badge">{esc(item.get("conf", ""))}</span>' if item.get("conf") else ""
        return f"""
        <div class="claim-card">
          <div class="claim-head">{conf}<div class="source-row">{render_source_tags(item.get('sources', []))}</div></div>
          <p>{esc(item.get('text', ''))}</p>
        </div>
        """
    if item_type == "callout":
        return render_callout(item)
    if item_type == "factJudge":
        return render_fact_judge(item)
    if item_type == "evidenceBox":
        return render_evidence_box(item)
    return ""


def render_sections(sections: list[dict[str, Any]]) -> str:
    blocks = []
    for section in sections:
        body = "\n".join(render_section_item(item) for item in section.get("items", []))
        blocks.append(
            f"""
            <section class="brief-section">
              <div class="section-head">{esc(section.get('domainTitle', ''))}</div>
              <div class="section-body">{body}</div>
            </section>
            """
        )
    return "\n".join(blocks)


def render_scorecard(rows: list[dict[str, Any]]) -> str:
    table_rows = []
    for row in rows:
        status_class = esc(row.get("status", "").lower().replace(" ", "-"))
        table_rows.append(
            f"""
            <tr>
              <td>{esc(row.get('indicator', ''))}</td>
              <td><span class="status-badge {status_class}">{esc(row.get('status', ''))}</span></td>
              <td>{esc(row.get('change', ''))}</td>
              <td>{esc(row.get('watch', ''))}</td>
            </tr>
            """
        )
    return "\n".join(table_rows)


def render_actions(actions: dict[str, list[str]]) -> str:
    groups = [
        ("Travel", actions.get("travel", [])),
        ("Supply Chain", actions.get("supplyChain", [])),
        ("Cyber", actions.get("cyber", [])),
        ("Comms", actions.get("comms", [])),
    ]
    cols = []
    for label, entries in groups:
        items = "".join(f"<li>{esc(entry)}</li>" for entry in entries)
        cols.append(
            f"""
            <div class="action-col">
              <h4>{esc(label)}</h4>
              <ul>{items}</ul>
            </div>
            """
        )
    return "\n".join(cols)


def docx_link_name(run_date) -> str:
    return f"epic_fury_{run_date.isoformat()}.docx"


def pdf_link_name(run_date) -> str:
    return f"epic_fury_{run_date.isoformat()}.pdf"


def render_html(run_date, brief_path: Path | None = None) -> Path:
    ensure_directories()
    paths = output_paths(run_date)
    brief = read_json(brief_path or paths["brief_json"])

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(brief['cfg']['eventTitle'])}</title>
  <style>
    :root {{
      --dark-blue: {COLORS['dark_blue']};
      --teal: {COLORS['teal']};
      --orange: {COLORS['orange']};
      --orange-bg: {COLORS['orange_bg']};
      --red: {COLORS['red']};
      --red-bg: {COLORS['red_bg']};
      --blue: {COLORS['blue']};
      --blue-bg: {COLORS['blue_bg']};
      --amber: {COLORS['amber']};
      --amber-bg: {COLORS['amber_bg']};
      --purple: {COLORS['purple']};
      --purple-bg: {COLORS['purple_bg']};
      --ink: {COLORS['ink']};
      --paper: #ffffff;
      --card: #f6f7f9;
      --border: #d7dee6;
    }}
    @page {{
      size: A4;
      margin: 1in;
      @bottom-center {{
        content: "ThreatWatch AI | " counter(page);
        color: #555;
        font-size: 10px;
      }}
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      font-family: Georgia, "Times New Roman", serif;
      background:
        radial-gradient(circle at top right, rgba(46,117,182,0.14), transparent 28%),
        linear-gradient(180deg, #eef4f8 0%, #ffffff 28%);
    }}
    a {{ color: var(--blue); text-decoration: none; }}
    .page {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 24px;
    }}
    .cover {{
      background: var(--dark-blue);
      color: #fff;
      padding: 32px;
      border-radius: 20px;
      box-shadow: 0 18px 40px rgba(27,58,92,0.18);
    }}
    .product {{
      letter-spacing: 0.16em;
      text-transform: uppercase;
      font-size: 0.82rem;
      opacity: 0.85;
      margin-bottom: 10px;
    }}
    .cover h1 {{
      margin: 0 0 10px;
      font-size: clamp(2rem, 4vw, 3.2rem);
      line-height: 1.05;
    }}
    .cover-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px 18px;
      margin-top: 18px;
      font-size: 0.98rem;
      color: #d7e7f4;
    }}
    .hero-links {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 22px;
    }}
    .hero-links a {{
      display: inline-flex;
      align-items: center;
      padding: 10px 16px;
      border-radius: 999px;
      background: rgba(255,255,255,0.12);
      color: white;
      border: 1px solid rgba(255,255,255,0.24);
    }}
    .summary-grid, .actions-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
      margin: 22px 0 32px;
    }}
    .summary-card, .action-col, .brief-section, .scorecard-wrap {{
      background: var(--paper);
      border: 1px solid var(--border);
      border-radius: 18px;
      box-shadow: 0 10px 26px rgba(24,33,43,0.06);
    }}
    .summary-card {{
      padding: 18px;
      border-top: 6px solid var(--blue);
    }}
    .summary-card.assessment {{ border-top-color: var(--purple); }}
    .summary-card.uncertainty {{ border-top-color: var(--amber); }}
    .summary-card-head, .claim-head {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 10px;
    }}
    .summary-type {{
      font-size: 0.8rem;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }}
    .conf-badge {{
      display: inline-flex;
      padding: 4px 10px;
      border-radius: 999px;
      background: var(--gray-bg);
      font-size: 0.78rem;
      font-weight: 700;
    }}
    .source-row {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 8px;
    }}
    .source-tag {{
      display: inline-flex;
      padding: 4px 8px;
      border-radius: 999px;
      background: #eef4f8;
      color: var(--blue);
      font-size: 0.74rem;
      font-weight: 700;
    }}
    .section-head {{
      background: var(--teal);
      color: white;
      padding: 14px 18px;
      border-radius: 18px 18px 0 0;
      font-weight: 700;
      letter-spacing: 0.03em;
    }}
    .section-body {{
      padding: 18px;
      display: grid;
      gap: 14px;
    }}
    h2 {{
      margin: 32px 0 14px;
      color: var(--dark-blue);
      font-size: 1.5rem;
    }}
    h3 {{
      margin: 0;
      color: var(--teal);
      font-size: 1.1rem;
    }}
    h4 {{
      margin: 0 0 10px;
      color: var(--dark-blue);
      font-size: 1rem;
    }}
    p {{ margin: 0; line-height: 1.6; }}
    .claim-card {{
      background: #fbfcfd;
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 16px;
    }}
    .callout {{
      border-left: 6px solid var(--blue);
      border-radius: 14px;
      padding: 16px;
    }}
    .callout-label {{
      font-weight: 700;
      margin-bottom: 10px;
    }}
    .callout.analyst, .callout.info {{
      background: var(--blue-bg);
      border-left-color: var(--blue);
    }}
    .callout.warning {{
      background: var(--orange-bg);
      border-left-color: var(--orange);
    }}
    .callout.alert {{
      background: var(--red-bg);
      border-left-color: var(--red);
    }}
    .callout.t4 {{
      background: var(--amber-bg);
      border-left-color: var(--amber);
    }}
    .callout.scope {{
      background: #f0f2f5;
      border-left-color: #6f7883;
    }}
    .callout.purple {{
      background: var(--purple-bg);
      border-left-color: var(--purple);
    }}
    .fact-judge {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }}
    .fact-judge > div {{
      background: #fbfcfd;
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 16px;
    }}
    .fact-judge ul, .action-col ul {{
      margin: 0;
      padding-left: 18px;
      display: grid;
      gap: 10px;
    }}
    .evidence-box {{
      border: 1px solid rgba(23,98,122,0.3);
      border-radius: 14px;
      overflow: hidden;
    }}
    .evidence-title {{
      background: rgba(23,98,122,0.09);
      color: var(--teal);
      padding: 12px 14px;
      font-weight: 700;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    th, td {{
      text-align: left;
      padding: 12px 14px;
      border-top: 1px solid #e6ebf1;
      vertical-align: top;
    }}
    .scorecard-wrap {{
      overflow: hidden;
      margin-top: 14px;
    }}
    .scorecard-wrap table th {{
      background: rgba(27,58,92,0.06);
      color: var(--dark-blue);
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .status-badge {{
      display: inline-flex;
      padding: 5px 10px;
      border-radius: 999px;
      background: #eef4f8;
      color: var(--blue);
      font-size: 0.76rem;
      font-weight: 700;
    }}
    .status-badge.critical {{ background: var(--red-bg); color: var(--red); }}
    .status-badge.elevated, .status-badge.building {{ background: var(--orange-bg); color: var(--orange); }}
    .status-badge.active, .status-badge.ongoing, .status-badge.confirmed {{ background: var(--blue-bg); color: var(--blue); }}
    .status-badge.pending, .status-badge.unknown, .status-badge.not-yet {{ background: var(--amber-bg); color: var(--amber); }}
    .action-col {{
      padding: 18px;
    }}
    footer {{
      margin: 28px 0 12px;
      color: #5a6672;
      font-size: 0.92rem;
      text-align: center;
    }}
    @media (max-width: 767px) {{
      .page {{ padding: 16px; }}
      .summary-grid, .actions-grid, .fact-judge {{ grid-template-columns: 1fr; }}
      .cover {{ padding: 24px; border-radius: 16px; }}
      th, td {{ padding: 10px; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="cover">
      <div class="product">{esc(brief['cfg']['productName'])}</div>
      <h1>{esc(brief['cfg']['eventTitle'])}</h1>
      <div>{esc(brief['cfg']['dayLabel'])}</div>
      <div class="cover-meta">
        <span>{esc(brief['cfg']['date'])}</span>
        <span>{esc(brief['cfg']['updateTime'])}</span>
        <span>{esc(brief['cfg']['classification'])}</span>
      </div>
      <div class="hero-links">
        <a href="../pdf/{esc(pdf_link_name(run_date))}">Download PDF</a>
        <a href="../docx/{esc(docx_link_name(run_date))}">Download DOCX</a>
      </div>
    </section>

    <h2>Executive Summary</h2>
    <section class="summary-grid">
      {render_exec_summary(brief.get('execSummary', []))}
    </section>

    {render_sections(brief.get('sections', []))}

    <h2>Scorecard</h2>
    <div class="scorecard-wrap">
      <table>
        <thead>
          <tr>
            <th>Indicator</th>
            <th>Status</th>
            <th>Change</th>
            <th>Watch</th>
          </tr>
        </thead>
        <tbody>
          {render_scorecard(brief.get('scorecard', []))}
        </tbody>
      </table>
    </div>

    <h2>Recommended Actions</h2>
    <section class="actions-grid">
      {render_actions(brief.get('actions', {}))}
    </section>

    <footer>
      {esc(brief['cfg']['productName'])} | {esc(brief['cfg']['classification'])}
    </footer>
  </div>
</body>
</html>
"""
    paths["html"].write_text(html_content)
    return paths["html"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the brief JSON to HTML.")
    parser.add_argument("--date", help="Run date in YYYY-MM-DD format")
    parser.add_argument("--brief", help="Optional brief JSON input path")
    args = parser.parse_args()
    run_date = parse_run_date(args.date)
    render_html(run_date, Path(args.brief) if args.brief else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
