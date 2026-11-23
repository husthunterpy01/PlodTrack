"""Build a one-page HTML dashboard + an Excel workbook for leadership from the database."""
import html
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

TEMPLATE = """<!doctype html><html><head><meta charset="utf-8"><title>Drilling Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>body{{font-family:system-ui,sans-serif;margin:24px;max-width:1000px;color:#222}}
.kpis{{display:flex;gap:16px;flex-wrap:wrap}}.kpi{{border:1px solid #ddd;border-radius:8px;padding:12px 18px}}
.kpi b{{display:block;font-size:1.6em}}table{{border-collapse:collapse;width:100%;margin:12px 0}}
td,th{{border-bottom:1px solid #eee;padding:6px;text-align:left;font-size:.9em}}</style></head><body>
<h1>Drilling Dashboard</h1><div class="kpis">{kpis}</div>
<h2>Metres per day</h2><canvas id="m" height="80"></canvas>
<h2>Cost per metre by day (AUD)</h2><canvas id="c" height="80"></canvas>
<h2>Contractor summary</h2>{contractors}
<h2>Flagged entries ({n_flags})</h2>{flags}
<script>const d={daily};
new Chart(document.getElementById('m'),{{type:'bar',data:{{labels:d.map(x=>x.plod_date),datasets:[{{label:'Metres',data:d.map(x=>x.metres)}}]}}}});
new Chart(document.getElementById('c'),{{type:'line',data:{{labels:d.map(x=>x.plod_date),datasets:[{{label:'$/m',data:d.map(x=>x.cost_per_metre)}}]}}}});
</script></body></html>"""


def main(db_path="data/processed/plods.db", out_dir="reports"):
    conn = sqlite3.connect(db_path)
    daily = pd.read_sql("SELECT * FROM v_daily_summary ORDER BY plod_date", conn)
    contractors = pd.read_sql("SELECT * FROM v_contractor_summary", conn)
    flags = pd.read_sql("""SELECT p.plod_date, p.contractor, p.rig_id, p.hole_id, a.rule, a.detail
                           FROM anomalies a JOIN drill_plods p USING (plod_id) ORDER BY p.plod_date""", conn)
    rejected = pd.read_sql("SELECT * FROM rejected_rows", conn)
    tot_m, tot_c = daily["metres"].sum(), daily["cost_aud"].sum()
    kpis = "".join(f'<div class="kpi">{l}<b>{v}</b></div>' for l, v in [
        ("Total metres", f"{tot_m:,.0f}"), ("Total cost", f"${tot_c:,.0f}"),
        ("Avg $/m", f"${tot_c / max(tot_m, 1):,.0f}"), ("Flagged", len(flags)), ("Rejected rows", len(rejected))])
    page = TEMPLATE.format(kpis=kpis, daily=json.dumps(daily.to_dict("records")),
                           contractors=contractors.to_html(index=False, border=0),
                           flags=flags.to_html(index=False, border=0, escape=True), n_flags=len(flags))
    out = Path(out_dir); out.mkdir(exist_ok=True)
    (out / "dashboard.html").write_text(page)
    with pd.ExcelWriter(out / "weekly_report.xlsx") as xw:
        daily.to_excel(xw, sheet_name="Daily", index=False)
        contractors.to_excel(xw, sheet_name="Contractors", index=False)
        flags.to_excel(xw, sheet_name="Flagged", index=False)
        rejected.to_excel(xw, sheet_name="Rejected rows", index=False)
    print(f"Wrote {out/'dashboard.html'} and {out/'weekly_report.xlsx'}")


if __name__ == "__main__":
    main(*sys.argv[1:])
