import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd
from plodtrack import anomalies, generate_sample_data, ingest


def build(tmp_path):
    raw = tmp_path / "raw"
    generate_sample_data.main(raw)
    db = tmp_path / "t.db"
    ingest.main(raw, db)
    return db


def test_ingest_rejects_bad_rows_and_loads_both_layouts(tmp_path):
    db = build(tmp_path)
    conn = sqlite3.connect(db)
    contractors = {r[0] for r in conn.execute("SELECT DISTINCT contractor FROM drill_plods")}
    assert contractors == {"Outback Drilling", "Kalgoorlie RC Services"}
    reasons = {r[0] for r in conn.execute("SELECT reason FROM rejected_rows")}
    assert "duplicate row" in reasons and "hours must be > 0" in reasons


def test_reingest_is_idempotent(tmp_path):
    db = build(tmp_path)
    n1 = sqlite3.connect(db).execute("SELECT COUNT(*) FROM drill_plods").fetchone()[0]
    ingest.main(tmp_path / "raw", db)
    n2 = sqlite3.connect(db).execute("SELECT COUNT(*) FROM drill_plods").fetchone()[0]
    assert n1 == n2


def test_anomalies_flag_planted_errors(tmp_path):
    db = build(tmp_path)
    df = pd.read_sql("SELECT * FROM drill_plods", sqlite3.connect(db))
    rules = {r for _, r, _ in anomalies.detect(df)}
    assert "IMPLAUSIBLE_RATE" in rules and "COST_PER_METRE_OUTLIER" in rules


def test_excel_workbook_has_live_constructs(tmp_path):
    import pandas as pd
    from openpyxl import load_workbook
    from plodtrack.excel_workbook import DATA_COLS, build
    df = pd.DataFrame([[pd.Timestamp("2026-09-01"), "A", "DAY", "R1", "H1", "RC", 100, 10, 1, 1500]],
                      columns=DATA_COLS)
    out = tmp_path / "w.xlsx"
    build(df, out)
    wb = load_workbook(out)
    assert "Plods" in wb["Plods"].tables
    assert str(wb["Summary"]["B6"].value).startswith("=SUMIFS(")
    assert wb["Plods"].data_validations.dataValidation
    assert {"FromDate", "MaxMph"} <= set(wb.defined_names)
