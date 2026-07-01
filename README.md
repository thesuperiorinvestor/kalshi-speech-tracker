# Kalshi Speech Tracker

A Streamlit analytics tool for Kalshi's **speech "mention" markets** — the contracts on *how many
times a speaker says a given word or phrase* in an event (rally, press conference, teleprompter
address, interview, signing, earnings call). It tracks markets, logs picks against an edge model,
and reports P&L / ROI so betting decisions are driven by data instead of gut.

> Built with **Python + Streamlit** and developed with Claude Code.

---

## What it does

- **Market + pick tracking** — stores mention markets and the picks made against them in SQLite,
  with outcomes (hit / miss / sold early / pending) and per-pick P&L.
- **Edge model** — classifies each pick by type — `historical_lock`, `contextual_override`,
  `structural_fade` — and buckets estimated edge (`>50`, `20–50`, `0–20`, `Negative`).
- **Event-type awareness** — separates rallies, pressers, teleprompter addresses, interviews,
  signings, and earnings calls, since a speaker's word rate varies wildly by format.
- **ROI analytics** — ROI on deployed capital, P&L by edge bucket / pick type / event type,
  visualized with Plotly.
- **Baseball HR predictor** (`hr_predictor.py`) — a separate module using `pybaseball` data to model
  home-run props.
- **Screenshot ingest** — `pytesseract` OCR to pull numbers off market screenshots.

## Tech stack

| | |
|---|---|
| App | Streamlit (single-file dashboard) |
| Data | SQLite (`init_db.py` bootstraps + seeds schema) |
| Analysis | pandas, Plotly |
| Sources | `requests`, `pybaseball` |
| OCR | pytesseract + Pillow |

## Run locally

```powershell
pip install -r requirements.txt
python -m streamlit run app.py
```

The database is created and seeded automatically on first run (`init_db()` / `seed_db()`), so no
manual setup is needed. Personal databases are git-ignored.

## Why I built it

Kalshi's speech markets look random but aren't — word rates cluster hard by speaker and event
format. I wanted a tool that turned that intuition into a tracked, measurable edge with honest ROI
accounting, rather than betting on vibes.
