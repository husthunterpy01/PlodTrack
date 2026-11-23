# PlodTrack — drilling data pipeline & dashboard

A small portfolio project built around the *Vacation Software Engineer* role at Valiant Gold
(tracking drill plods, costs and site data; ingesting contractor Excel files; dashboards; AI assists).
All data is **synthetic**. No real company data is used.

| Job requirement | Where it lives |
|---|---|
| Get contractor Excel data in with less manual entry | `src/plodtrack/ingest.py` – per-contractor column mapping, title-row detection, cleaning, validation, idempotent reload |
| SQL | `sql/schema.sql` – constraints, unique key, summary views |
| Python scripting | `src/plodtrack/` |
| Track drill plods & costs | `drill_plods` table, `v_daily_summary`, `v_contractor_summary` |
| Dashboards & reports for leadership | `report.py` → `reports/dashboard.html` + `reports/weekly_report.xlsx` |
| Flag unusual entries | `anomalies.py` – explainable rules (physical m/h limits, robust MAD cost outliers) |
| AI, with sense to check output | `ai_extract.py` – LLM extraction whose output is validated and routed to human review |
| Excel beyond basic formulas | see *Excel line* below |

## Run it
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=src
python -m plodtrack.generate_sample_data
python -m plodtrack.ingest
python -m plodtrack.anomalies
python -m plodtrack.report        # open reports/dashboard.html
pytest
```

## Ideas to extend
- Add a costs/budget table and variance-to-budget view
- Mining inventory (stockpile tonnes & grade) tables
- Safety metrics (LTIFR, near-miss counts) tab
- Swap SQLite for Postgres; schedule ingest on a folder watcher
- Streamlit front end for geologists to review flagged rows

## Excel line for the application
Replace with something you have truly done, e.g. "Built a workbook using Power Query and XLOOKUP/INDEX-MATCH
to consolidate monthly files, with pivot tables and conditional formatting for exceptions."
