"""Load contractor Excel files into SQLite, normalising each contractor's layout."""
import sqlite3
import sys
from pathlib import Path

import pandas as pd

# One mapping per contractor: canonical name -> header used in their file.
CONTRACTORS = {
    "outback_drilling": {
        "name": "Outback Drilling",
        "columns": {"Date": "plod_date", "Shift": "shift", "Rig": "rig_id", "Hole ID": "hole_id",
                    "Type": "drill_type", "Metres": "metres_drilled", "Hours": "hours_worked",
                    "Standby Hrs": "standby_hours", "Cost ($)": "cost_aud"},
    },
    "kalgoorlie_rc": {
        "name": "Kalgoorlie RC Services",
        "columns": {"Plod Date": "plod_date", "Shift": "shift", "Rig No.": "rig_id", "Hole": "hole_id",
                    "Drill Type": "drill_type", "Total Metres": "metres_drilled",
                    "Operating Hours": "hours_worked", "Standby (h)": "standby_hours",
                    "Invoice AUD": "cost_aud"},
    },
}
REQUIRED = ["plod_date", "shift", "rig_id", "hole_id", "drill_type", "metres_drilled",
            "hours_worked", "cost_aud"]
HOLES_CSV = Path(__file__).resolve().parents[2] / "data" / "external" / "wa_drillholes" / "holes.csv"
SCHEMA = Path(__file__).resolve().parents[2] / "sql" / "schema.sql"


def find_header_row(path, first_header):
    """Contractors often put titles above the table; find the row holding the first column header."""
    raw = pd.read_excel(path, header=None)
    for i, row in raw.iterrows():
        if first_header in row.astype(str).str.strip().values:
            return i
    raise ValueError(f"header '{first_header}' not found in {path.name}")


def identify(path):
    stem = path.stem.lower()
    for key, cfg in CONTRACTORS.items():
        if stem.startswith(key):
            return cfg
    raise ValueError(f"no contractor mapping for {path.name}")


def clean(df, path, contractor):
    """Return (good_rows, rejected[(row_number, reason)])."""
    rejected = []
    df = df.copy()
    df["_row"] = df.index + 2  # approximate Excel row number
    df["plod_date"] = pd.to_datetime(df["plod_date"], dayfirst=True, errors="coerce")
    df["shift"] = df["shift"].astype(str).str.strip().str.upper()
    df["drill_type"] = df["drill_type"].astype(str).str.strip().str.upper()
    df["rig_id"] = df["rig_id"].astype(str).str.strip()
    df["hole_id"] = df["hole_id"].astype(str).str.strip()
    for c in ("metres_drilled", "hours_worked", "cost_aud"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if "standby_hours" not in df:
        df["standby_hours"] = 0
    df["standby_hours"] = pd.to_numeric(df["standby_hours"], errors="coerce").fillna(0)

    def reason(r):
        if pd.isna(r.plod_date): return "invalid date"
        if r["shift"] not in ("DAY", "NIGHT"): return f"bad shift '{r['shift']}'"
        if r.drill_type not in ("RC", "DD", "AC"): return f"bad drill type '{r.drill_type}'"
        if pd.isna(r.metres_drilled) or r.metres_drilled < 0: return "invalid metres"
        if pd.isna(r.hours_worked) or r.hours_worked <= 0: return "hours must be > 0"
        if pd.isna(r.cost_aud) or r.cost_aud < 0: return "invalid cost"
        return None

    df["_reason"] = df.apply(reason, axis=1)
    dup = df.duplicated(subset=["plod_date", "shift", "rig_id", "hole_id"], keep="first") & df["_reason"].isna()
    df.loc[dup, "_reason"] = "duplicate row"
    for _, r in df[df["_reason"].notna()].iterrows():
        rejected.append((int(r["_row"]), r["_reason"]))
    good = df[df["_reason"].isna()].copy()
    good["plod_date"] = good["plod_date"].dt.strftime("%Y-%m-%d")
    good["contractor"] = contractor
    good["source_file"] = path.name
    return good, rejected


def ingest_file(conn, path):
    cfg = identify(path)
    first_header = next(iter(cfg["columns"]))
    header = find_header_row(path, first_header)
    df = pd.read_excel(path, header=header)
    df.columns = [str(c).strip() for c in df.columns]
    missing = [h for h in cfg["columns"] if h not in df.columns and cfg["columns"][h] in REQUIRED]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}")
    df = df.rename(columns=cfg["columns"])[list(cfg["columns"].values())].dropna(how="all")
    good, rejected = clean(df, path, cfg["name"])

    cols = ["source_file", "contractor", "plod_date", "shift", "rig_id", "hole_id", "drill_type",
            "metres_drilled", "hours_worked", "standby_hours", "cost_aud"]
    conn.execute("DELETE FROM drill_plods WHERE source_file = ?", (path.name,))  # idempotent re-load
    conn.execute("DELETE FROM rejected_rows WHERE source_file = ?", (path.name,))
    conn.executemany(
        f"INSERT OR IGNORE INTO drill_plods ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        good[cols].itertuples(index=False, name=None))
    conn.executemany("INSERT INTO rejected_rows (source_file,row_number,reason) VALUES (?,?,?)",
                     [(path.name, n, r) for n, r in rejected])
    return len(good), len(rejected)


def load_holes(conn, csv_path):
    """Load real WA drillhole collars. Hole IDs that appear more than once are ambiguous and skipped."""
    h = pd.read_csv(csv_path)
    ambiguous = h["holeid"].duplicated(keep=False)
    h = h[~ambiguous].copy()
    for c in ("period_from", "period_to"):
        h[c] = pd.to_datetime(h[c], unit="ms", errors="coerce").dt.strftime("%Y-%m-%d")
    conn.execute("DELETE FROM holes")
    conn.executemany(
        "INSERT INTO holes VALUES (?,?,?,?,?,?,?,?,?)",
        h[["holeid", "holetype", "maxdepth", "operator", "project", "latitude", "longitude",
           "period_from", "period_to"]].itertuples(index=False, name=None))
    return len(h), int(ambiguous.sum())


def main(raw_dir="data/raw", db_path="data/processed/plods.db"):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA.read_text())
    if HOLES_CSV.exists():
        n, skipped = load_holes(conn, HOLES_CSV)
        print(f"holes: loaded {n} real drillholes ({skipped} ambiguous duplicate-ID rows skipped)")
    for f in sorted(Path(raw_dir).glob("*.xlsx")):
        ok, bad = ingest_file(conn, f)
        print(f"{f.name}: loaded {ok}, rejected {bad}")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main(*sys.argv[1:])
