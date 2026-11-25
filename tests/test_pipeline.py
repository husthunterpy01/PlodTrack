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


GOOD_PLOD = {"plod_date": "2026-09-01", "shift": "DAY", "rig_id": "OB1", "hole_id": "H1", "drill_type": "RC",
             "metres_drilled": 80, "hours_worked": 10, "standby_hours": 1, "cost_aud": 1200}


def test_ai_validate_matches_ingest_rules():
    from plodtrack.ai_extract import validate
    assert validate(GOOD_PLOD) == []
    assert validate({**GOOD_PLOD, "cost_aud": None}) == []          # cost may be unstated
    assert validate({**GOOD_PLOD, "hours_worked": 0}) == ["hours_worked"]
    assert validate({**GOOD_PLOD, "plod_date": "yesterday"}) == ["plod_date"]
    assert validate({**GOOD_PLOD, "hole_id": None}) == ["hole_id"]
    assert validate({**GOOD_PLOD, "metres_drilled": True}) == ["metres_drilled"]
    assert validate({**GOOD_PLOD, "shift": "EVENING", "drill_type": "XX"}) == ["shift", "drill_type"]
    assert validate("nope") == ["not_an_object"]


SOURCE_TEXT = ("Day shift 2026-09-01 rig OB1 hole H1 RC drilled 80 m in 10 h, standby 1 h, cost 1200")


def test_ai_extract_handles_messy_model_output():
    import json
    import types
    from unittest import mock
    from plodtrack import ai_extract

    def run(text):
        client = mock.MagicMock()
        client.messages.create.return_value = types.SimpleNamespace(content=[types.SimpleNamespace(text=text)])
        with mock.patch("anthropic.Anthropic", return_value=client):
            return ai_extract.extract(SOURCE_TEXT)

    body = json.dumps(GOOD_PLOD)
    for text in (body, f"```json\n{body}\n```", f"Here you go: {body}"):
        assert run(text)["needs_review"] == []
    bad = run("I could not find a plod in this report")
    assert bad["record"] is None and bad["needs_review"] == ["unparseable_output"]
    assert run(json.dumps({**GOOD_PLOD, "hours_worked": 0}))["needs_review"] == ["hours_worked"]


def test_ai_ground_flags_values_not_in_source():
    from plodtrack.ai_extract import ground
    text = "Evening shift 2026-09-06 rig OB1 hole HOP125 RC 59.4 m in 9.1 h cost 1076.27"
    rec = {**GOOD_PLOD, "shift": "NIGHT", "rig_id": "OB1", "hole_id": "HOP125", "metres_drilled": 59.4,
           "hours_worked": 9.1, "standby_hours": 0, "cost_aud": 1076.27}
    assert ground(rec, text) == ["ungrounded:shift"]
    assert ground({**rec, "shift": "DAY", "metres_drilled": 60}, "Day shift rig OB1 hole HOP125 RC 59.4 m 9.1 h 1076.27") \
        == ["ungrounded:metres_drilled"]
