"""Flag unusual plod entries. Simple, explainable rules a geologist can sanity-check."""
import sqlite3
import sys

import pandas as pd

MAX_MPH = {"RC": 20, "DD": 8, "AC": 30}  # physical upper bound, metres per working hour


def detect(df):
    """df: drill_plods rows. Returns list of (plod_id, rule, detail)."""
    out = []
    df = df.copy()
    df["mph"] = df["metres_drilled"] / (df["hours_worked"] - df["standby_hours"]).clip(lower=0.1)
    df["cpm"] = df["cost_aud"] / df["metres_drilled"].where(df["metres_drilled"] > 0)

    for r in df.itertuples():
        if r.mph > MAX_MPH[r.drill_type]:
            out.append((r.plod_id, "IMPLAUSIBLE_RATE",
                        f"{r.metres_drilled} m in {r.hours_worked - r.standby_hours:.1f} productive h "
                        f"= {r.mph:.1f} m/h (max {MAX_MPH[r.drill_type]} for {r.drill_type})"))
        if r.standby_hours > r.hours_worked:
            out.append((r.plod_id, "STANDBY_EXCEEDS_HOURS", f"{r.standby_hours} > {r.hours_worked}"))

    # Cost per metre outliers within each drill type (robust: median/MAD)
    for dtype, g in df.dropna(subset=["cpm"]).groupby("drill_type"):
        if len(g) < 8:
            continue
        med = g["cpm"].median()
        mad = (g["cpm"] - med).abs().median() or 1e-9
        z = 0.6745 * (g["cpm"] - med) / mad
        for pid, zi, cpm in zip(g["plod_id"], z, g["cpm"]):
            if abs(zi) > 3.5:
                out.append((pid, "COST_PER_METRE_OUTLIER",
                            f"${cpm:,.0f}/m vs median ${med:,.0f}/m for {dtype} (robust z={zi:.1f})"))
    return out


def main(db_path="data/processed/plods.db"):
    conn = sqlite3.connect(db_path)
    df = pd.read_sql("SELECT * FROM drill_plods", conn)
    flags = detect(df)
    conn.execute("DELETE FROM anomalies")
    conn.executemany("INSERT INTO anomalies (plod_id, rule, detail) VALUES (?,?,?)", flags)
    conn.commit()
    print(f"Flagged {len(flags)} anomalies across {df.shape[0]} plods")
    conn.close()


if __name__ == "__main__":
    main(*sys.argv[1:])
