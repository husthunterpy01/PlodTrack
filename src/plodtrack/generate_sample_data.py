"""Create fake contractor drill-plod Excel files (each contractor uses a different layout,
like real life) with a few deliberately bad rows so the pipeline has something to catch."""
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

RATES = {"Outback Drilling": 95, "Kalgoorlie RC Services": 88}  # AUD per hour-ish


def _rows(contractor, rig_prefix, n_days, seed):
    rng = random.Random(seed)
    start = date(2026, 9, 1)
    rows = []
    hole = 1
    for d in range(n_days):
        day = start + timedelta(days=d)
        for shift in ("DAY", "NIGHT"):
            for rig in (f"{rig_prefix}1", f"{rig_prefix}2"):
                dt = rng.choice(["RC", "RC", "RC", "DD", "AC"])
                hours = round(rng.uniform(9, 11.5), 1)
                standby = round(rng.choice([0, 0, 0.5, 1, 2]), 1)
                mph = {"RC": 9, "DD": 3.5, "AC": 14}[dt]
                metres = round(max(0, (hours - standby) * rng.gauss(mph, mph * 0.12)), 1)
                cost = round(hours * RATES[contractor] * (1.6 if dt == "DD" else 1) * rng.uniform(0.97, 1.03)
                             + metres * 4, 2)
                rows.append(dict(date=day, shift=shift, rig=rig, hole=f"VGR{26000 + hole:05d}", type=dt,
                                 metres=metres, hours=hours, standby=standby, cost=cost))
                hole += 1
    return rows


def main(out_dir="data/raw"):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Contractor A: tidy-ish columns
    a = pd.DataFrame(_rows("Outback Drilling", "OB", 30, 1))
    a.loc[40, "metres"] = 412.0          # implausible metres
    a.loc[55, "cost"] = a.loc[55, "cost"] * 6  # cost spike
    a.loc[60, "hours"] = 0               # invalid
    a = a.rename(columns={"date": "Date", "shift": "Shift", "rig": "Rig", "hole": "Hole ID",
                          "type": "Type", "metres": "Metres", "hours": "Hours",
                          "standby": "Standby Hrs", "cost": "Cost ($)"})
    a = pd.concat([a, a.iloc[[5]]])     # exact duplicate row
    a.to_excel(out / "outback_drilling_sep2026.xlsx", index=False, sheet_name="Plods")

    # Contractor B: different headers, title rows above the table, text dates
    b = pd.DataFrame(_rows("Kalgoorlie RC Services", "KR", 30, 2))
    b["date"] = b["date"].map(lambda d: d.strftime("%d/%m/%Y"))
    b.loc[12, "type"] = "rc "            # messy casing/whitespace
    b = b.rename(columns={"date": "Plod Date", "shift": "Shift", "rig": "Rig No.", "hole": "Hole",
                          "type": "Drill Type", "metres": "Total Metres", "hours": "Operating Hours",
                          "standby": "Standby (h)", "cost": "Invoice AUD"})
    path = out / "kalgoorlie_rc_sep2026.xlsx"
    with pd.ExcelWriter(path) as xw:
        pd.DataFrame([["Kalgoorlie RC Services - Daily Plods"], ["Project: Valiant North"], []]).to_excel(
            xw, index=False, header=False, sheet_name="Sheet1")
        b.to_excel(xw, index=False, sheet_name="Sheet1", startrow=3)
    print(f"Wrote sample files to {out}")


if __name__ == "__main__":
    main()
