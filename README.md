# ThreatWatch: Iran Conflict Monitor

**Automated daily OSINT intelligence brief pipeline — Operation Epic Fury**

Fetches T1/T2 open-source intelligence sources every morning, calls Claude AI to generate a structured intelligence brief, runs a QC audit, and exports delivery-ready DOCX, PDF, HTML, and Markdown — plus a live web dashboard and optional email delivery to clients.

This is the pipeline powering [ThreatWatch AI](https://wagenerframeworks.com), a commercial threat intelligence subscription service for corporate security teams.

---

## What It Produces

Each run outputs:

| Format | Location | Use |
|--------|----------|-----|
| DOCX | `output/docx/` | Styled Word doc — cover page, color callouts, tables |
| PDF | `output/pdf/` | Shareable client-ready PDF via WeasyPrint |
| HTML | `output/html/` | Self-contained HTML brief, no CDN deps |
| Markdown | `output/md/` | Retention copy, searchable |
| JSON | `output/json/` | Structured brief + OSINT package + QC report |
| Dashboard | `dashboard/` | Static web dashboard, latest brief auto-loaded |

---

## Pipeline Architecture

```
┌─────────────────────────────────────────────────────────┐
│  OSINT Fetch — T1/T2/T3 RSS + HTTP (feedparser)         │
│  CENTCOM · White House · Pentagon · Reuters · AP · CNN  │
│  Military Times · Breaking Defense · The War Zone       │
│  CSIS · Defense One · SOF News · CISA advisories        │
└────────────────────────┬────────────────────────────────┘
                         │  relevance filter + dedup
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Claude AI Brief Generation                             │
│  Structured JSON schema: cfg · execSummary · sections  │
│  scorecard · actions · sourceRegistry · sourcesAppendix│
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Multi-format Export                                    │
│  DOCX (Node.js renderer) · PDF · HTML · Markdown       │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│  QC Sub-agent                                           │
│  Schema · content quality · file checks · source rules │
│  Blocks delivery on failure                             │
└────────────────────────┬────────────────────────────────┘
                         │  --deliver flag only
                         ▼
              Email delivery to client list
```

---

## Quick Start

```bash
git clone https://github.com/bwagene1/threatwatch-iran-monitor
cd threatwatch-iran-monitor
cp .env.example .env        # fill in your ANTHROPIC_API_KEY
bash setup.sh
python3 pipeline.py
```

Dry-run (no API call, uses stub brief):

```bash
python3 pipeline.py --dry-run
```

---

## Configuration

`.env` keys (copy from `.env.example`):

```
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-6
```

### DOCX Renderer

The DOCX output requires the Node.js renderer (`brief-system/`). If you cloned this repo standalone, either:

- Set `TW_RENDERER_DIR=/path/to/brief-system` in `.env`, or
- Skip DOCX — PDF, HTML, and Markdown still generate without it

The renderer is available in the parent `threatwatch-ai` repo.

### Prompt Files

`prompts/brief_writer_system.md` — the Claude system prompt defining the brief schema  
`prompts/brief_starter.json` — the JSON schema template

You can swap in your own by setting `TW_BRIEF_PROMPT` and `TW_BRIEF_STARTER` in `.env`.

---

## Dashboard

```bash
python3 -m http.server 8755
# Open http://localhost:8755/dashboard/
```

Shows latest brief, last 7 days of history, links to all export formats.

---

## Cron Setup (Daily 6 AM)

```bash
crontab -e
# Add:
0 6 * * * /path/to/threatwatch-iran-monitor/run.sh
```

---

## Email Delivery

1. Set up Gmail App Password: [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
2. Add `SMTP_*` keys to `.env` (see `.env.example`)
3. Edit `clients.json` to add your client list
4. Run with delivery:

```bash
python3 pipeline.py --deliver
```

---

## QC Agent

Every run is audited by `qc_agent.py` before success is logged:

- **Schema:** exec summary order, scorecard row count (8–12), actions structure, source registry
- **Content:** no placeholder text, correct date, no empty text fields
- **Source rules:** T4-only claims capped at LOW confidence; at least 3 HIGH-confidence claims
- **File checks:** DOCX > 10KB, PDF > 20KB, HTML > 2KB, Markdown > 500 chars

Exit 0 = all critical checks pass. Exit 1 = block delivery, alert operator.

---

## Project Structure

```
threatwatch-iran-monitor/
├── pipeline.py           # Main orchestrator
├── fetch_osint.py        # T1/T2/T3 OSINT fetcher (RSS + HTTP)
├── generate_brief.py     # Claude API → structured brief JSON
├── html_renderer.py      # Brief JSON → styled self-contained HTML
├── pdf_exporter.py       # HTML → PDF (WeasyPrint)
├── md_exporter.py        # Brief JSON → Markdown
├── qc_agent.py           # QC audit sub-agent
├── product_sheet.py      # Generates product one-pager PDF
├── common.py             # Shared constants and utilities
├── prompts/
│   ├── brief_writer_system.md   # Claude system prompt / brief schema
│   └── brief_starter.json       # JSON schema template
├── dashboard/
│   └── index.html        # Static web dashboard
├── output/               # Generated files (gitignored)
├── logs/                 # Pipeline logs (gitignored)
├── clients.json          # Client delivery list (sample)
├── setup.sh              # One-time installer
├── run.sh                # Cron-safe wrapper
└── .env.example          # Config template
```

---

## Dependencies

- Python 3.10+: `anthropic`, `python-dotenv`, `feedparser`, `requests`, `weasyprint`
- Node.js (optional, for DOCX output)

Install: `bash setup.sh`

---

## Built By

Brandon Wagener — Army veteran (173rd Airborne Brigade, Intelligence Analyst), Security Operations professional, MS AI in Business candidate (W.P. Carey), founder of Wagener Framework LLC.

- GitHub: [@bwagene1](https://github.com/bwagene1)
- ThreatWatch AI service: [wagenerframeworks.com](https://wagenerframeworks.com)

---

*Open-source intelligence only. Not for redistribution of brief content. This tool and its outputs are provided for informational purposes. ThreatWatch AI is a product of Wagener Framework LLC.*
