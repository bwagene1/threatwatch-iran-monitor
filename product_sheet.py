#!/usr/bin/env python3
from __future__ import annotations

import argparse

from common import ensure_directories, output_paths, parse_run_date
from pdf_exporter import require_weasyprint


def build_product_sheet_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <style>
    @page {
      size: A4;
      margin: 0.65in;
    }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: #18212B;
      background:
        linear-gradient(140deg, rgba(27,58,92,0.08), transparent 40%),
        linear-gradient(180deg, #f3f8fb 0%, #ffffff 42%);
    }
    .sheet {
      border: 1px solid #d7dee6;
      border-radius: 24px;
      overflow: hidden;
      box-shadow: 0 18px 40px rgba(24,33,43,0.08);
    }
    .hero {
      background: #1B3A5C;
      color: white;
      padding: 28px 34px;
    }
    .eyebrow {
      text-transform: uppercase;
      letter-spacing: 0.18em;
      font-size: 12px;
      opacity: 0.8;
      margin-bottom: 10px;
    }
    h1 {
      margin: 0 0 10px;
      font-size: 34px;
      line-height: 1.08;
    }
    .tagline {
      font-size: 18px;
      color: #d6eef5;
    }
    .body {
      padding: 28px 34px 22px;
      display: grid;
      grid-template-columns: 1.25fr 0.95fr;
      gap: 24px;
    }
    .card {
      border: 1px solid #d7dee6;
      border-radius: 18px;
      padding: 18px;
      background: #fbfcfd;
      margin-bottom: 16px;
    }
    h2 {
      margin: 0 0 12px;
      color: #17627A;
      font-size: 20px;
    }
    ul {
      margin: 0;
      padding-left: 18px;
      display: grid;
      gap: 9px;
    }
    .pricing {
      background: #FFF2CC;
      border-color: #D8C07A;
    }
    .pricing strong {
      display: block;
      margin-bottom: 8px;
      font-size: 20px;
      color: #7F4F00;
    }
    table {
      width: 100%;
      border-collapse: collapse;
    }
    th, td {
      border-top: 1px solid #e5ebf1;
      padding: 10px 12px;
      text-align: left;
      vertical-align: top;
    }
    th {
      background: rgba(27,58,92,0.06);
      color: #1B3A5C;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .footer {
      padding: 0 34px 28px;
      color: #5a6672;
      font-size: 13px;
    }
  </style>
</head>
<body>
  <div class="sheet">
    <div class="hero">
      <div class="eyebrow">ThreatWatch AI</div>
      <h1>Iran Conflict Monitor</h1>
      <div class="tagline">Daily open-source intelligence briefings for corporate security teams</div>
    </div>
    <div class="body">
      <div>
        <div class="card">
          <h2>What's Included</h2>
          <ul>
            <li>Daily brief delivered in PDF and DOCX formats</li>
            <li>Cyber threat feed with Iran-linked actor monitoring</li>
            <li>Five-point executive summary for rapid leadership review</li>
            <li>Operational scorecard with watch indicators</li>
            <li>Recommended actions for travel, supply chain, cyber, and comms</li>
          </ul>
        </div>
        <div class="card">
          <h2>Who It's For</h2>
          <ul>
            <li>Security directors and GSOC leaders</li>
            <li>Travel managers and crisis response teams</li>
            <li>Supply chain and continuity leads</li>
            <li>Executive leadership requiring concise daily threat context</li>
          </ul>
        </div>
        <div class="card pricing">
          <strong>$299/month</strong>
          Iran Monitor standalone
          <br><br>
          <strong>$999/month</strong>
          Full ThreatWatch service
        </div>
      </div>
      <div>
        <div class="card">
          <h2>Sample Scorecard</h2>
          <table>
            <thead>
              <tr>
                <th>Indicator</th>
                <th>Status</th>
                <th>Watch</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Regional airspace reliability</td>
                <td>ELEVATED</td>
                <td>Airline cancellations or official airspace closures</td>
              </tr>
              <tr>
                <td>Iran-linked cyber activity</td>
                <td>ACTIVE</td>
                <td>CISA or vendor advisory citing actor movement</td>
              </tr>
              <tr>
                <td>Diplomatic off-ramp</td>
                <td>PENDING</td>
                <td>Named mediation channel confirmed publicly</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="card">
          <h2>Contact</h2>
          <p>Brandon Wagener<br>[add Brandon email here]</p>
        </div>
      </div>
    </div>
    <div class="footer">Wagener Framework LLC | Open-source intelligence only</div>
  </div>
</body>
</html>"""


def generate_product_sheet(run_date) -> str:
    ensure_directories()
    paths = output_paths(run_date)
    HTML = require_weasyprint()
    HTML(string=build_product_sheet_html()).write_pdf(str(paths["product_pdf"]))
    return str(paths["product_pdf"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the Iran Monitor product-sheet PDF.")
    parser.add_argument("--date", help="Run date in YYYY-MM-DD format")
    args = parser.parse_args()
    run_date = parse_run_date(args.date)
    generate_product_sheet(run_date)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
