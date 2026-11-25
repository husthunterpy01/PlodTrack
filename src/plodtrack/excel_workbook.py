"""Build an *interactive* Excel workbook (not just a data dump) from the plods database.

Showcases real Excel constructs, all live in the file so a geologist can change an input and
watch everything recalculate:
  - Excel Table (ListObject) with structured references and calculated columns
  - SUMIFS / COUNTIFS / IFERROR / INDEX-MATCH formulas (no hard-coded results)
  - Named ranges and an assumptions sheet that drives the flag rule (same limits as anomalies.py)
  - Data validation (drop-downs, numeric limits) to stop bad manual entry
  - Conditional formatting (rule-based highlight, data bars, colour scale)
  - Native charts, frozen panes, number formats, print setup
Usage: python -m plodtrack.excel_workbook
"""
import sqlite3
import sys
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.formatting.rule import ColorScaleRule, DataBarRule, FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

from plodtrack.anomalies import MAX_MPH

HEAD = PatternFill("solid", fgColor="1F3864")
INPUT = PatternFill("solid", fgColor="FFF2CC")  # yellow = cell you are meant to edit
BOLD_W = Font(bold=True, color="FFFFFF")
RED = PatternFill("solid", bgColor="F8CBAD", fgColor="F8CBAD")

DATA_COLS = ["plod_date", "contractor", "shift", "rig_id", "hole_id", "drill_type",
             "metres_drilled", "hours_worked", "standby_hours", "cost_aud"]


def _this(col):
    return f"Plods[[#This Row],[{col}]]"


def _header(ws, row, labels, col=1):
    for i, text in enumerate(labels):
        c = ws.cell(row=row, column=col + i, value=text)
        c.fill, c.font = HEAD, BOLD_W
        c.alignment = Alignment(horizontal="center", wrap_text=True)


def build(df, out_path):
    wb = Workbook()

    # ---------- Limits (assumptions that drive the formulas) ----------
    lim = wb.active
    lim.title = "Limits"
    lim["A1"], lim["A1"].font = "Assumptions - edit the yellow cells, flags update everywhere", Font(bold=True, size=13)
    _header(lim, 3, ["drill_type", "max_metres_per_hour"])
    for i, (k, v) in enumerate(MAX_MPH.items(), start=4):
        lim.cell(row=i, column=1, value=k)
        c = lim.cell(row=i, column=2, value=v)
        c.fill = INPUT
    last_lim = 3 + len(MAX_MPH)
    wb.defined_names["DrillTypes"] = DefinedName("DrillTypes", attr_text=f"Limits!$A$4:$A${last_lim}")
    wb.defined_names["MaxMph"] = DefinedName("MaxMph", attr_text=f"Limits!$B$4:$B${last_lim}")
    lim.column_dimensions["A"].width = lim.column_dimensions["B"].width = 22

    # ---------- Plods: Excel Table + calculated columns ----------
    ws = wb.create_sheet("Plods", 0)
    calc = ["productive_hours", "metres_per_hour", "cost_per_metre", "max_mph", "rate_check"]
    cols = DATA_COLS + calc
    ws.append(cols)
    for r in df[DATA_COLS].itertuples(index=False):
        ws.append(list(r))
    n = len(df)
    last = n + 1
    # calculated columns use structured references (Plods[[#This Row],[col]])
    for row in range(2, last + 1):
        ws.cell(row=row, column=11, value=f"={_this('hours_worked')}-{_this('standby_hours')}")
        ws.cell(row=row, column=12,
                value=f"=IFERROR({_this('metres_drilled')}/{_this('productive_hours')},0)")
        ws.cell(row=row, column=13,
                value=f"=IFERROR({_this('cost_aud')}/{_this('metres_drilled')},0)")
        ws.cell(row=row, column=14,
                value=f"=INDEX(MaxMph,MATCH({_this('drill_type')},DrillTypes,0))")
        ws.cell(row=row, column=15,
                value=f'=IF({_this("metres_per_hour")}>{_this("max_mph")},"CHECK","")')
        ws.cell(row=row, column=1).number_format = "yyyy-mm-dd"
        ws.cell(row=row, column=10).number_format = '"$"#,##0.00'
        ws.cell(row=row, column=13).number_format = '"$"#,##0.00'
        ws.cell(row=row, column=12).number_format = "0.0"
    tab = Table(displayName="Plods", ref=f"A1:{get_column_letter(len(cols))}{last}")
    tab.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    ws.add_table(tab)
    ws.freeze_panes = "A2"
    for i, name in enumerate(cols, start=1):
        ws.column_dimensions[get_column_letter(i)].width = max(14, len(name) + 3)

    # data validation: stop bad manual entry at the source
    dv_shift = DataValidation(type="list", formula1='"DAY,NIGHT"', allow_blank=False,
                              showErrorMessage=True, errorTitle="Shift", error="Choose DAY or NIGHT")
    dv_type = DataValidation(type="list", formula1="=DrillTypes", allow_blank=False,
                             showErrorMessage=True, errorTitle="Drill type", error="Pick a type from the Limits sheet")
    dv_num = DataValidation(type="decimal", operator="greaterThanOrEqual", formula1="0",
                            showErrorMessage=True, errorTitle="Number", error="Must be 0 or more")
    for dv, rng in [(dv_shift, f"C2:C{last + 500}"), (dv_type, f"F2:F{last + 500}"),
                    (dv_num, f"G2:J{last + 500}")]:
        ws.add_data_validation(dv)
        dv.add(rng)

    # conditional formatting
    ws.conditional_formatting.add(f"A2:{get_column_letter(len(cols))}{last}",
                                  FormulaRule(formula=['$O2="CHECK"'], fill=RED))
    ws.conditional_formatting.add(f"G2:G{last}", DataBarRule(start_type="num", start_value=0,
                                                              end_type="max", color="5B9BD5"))
    ws.conditional_formatting.add(f"M2:M{last}", ColorScaleRule(start_type="min", start_color="C6EFCE",
                                                                mid_type="percentile", mid_value=50,
                                                                mid_color="FFFFFF",
                                                                end_type="max", end_color="F4B183"))

    # ---------- Summary: formulas over the table, driven by input cells ----------
    sm = wb.create_sheet("Summary", 0)
    sm["A1"], sm["A1"].font = "Drilling summary (live formulas over the Plods table)", Font(bold=True, size=14)
    sm["A3"], sm["B3"], sm["A4"], sm["B4"] = "From date", df["plod_date"].min(), "To date", df["plod_date"].max()
    for c in ("B3", "B4"):
        sm[c].fill, sm[c].number_format = INPUT, "yyyy-mm-dd"
    sm["C3"] = "<- change the dates; every number below recalculates"
    wb.defined_names["FromDate"] = DefinedName("FromDate", attr_text="Summary!$B$3")
    wb.defined_names["ToDate"] = DefinedName("ToDate", attr_text="Summary!$B$4")

    window = "Plods[plod_date],\">=\"&FromDate,Plods[plod_date],\"<=\"&ToDate"
    kpis = [("Total metres", f"=SUMIFS(Plods[metres_drilled],{window})", "#,##0"),
            ("Total cost (AUD)", f"=SUMIFS(Plods[cost_aud],{window})", '"$"#,##0'),
            ("Average $/m", "=IFERROR(B7/B6,0)", '"$"#,##0.00'),
            ("Plods flagged CHECK", f'=COUNTIFS(Plods[rate_check],"CHECK",{window})', "0")]
    for i, (label, f, fmt) in enumerate(kpis, start=6):
        sm.cell(row=i, column=1, value=label).font = Font(bold=True)
        c = sm.cell(row=i, column=2, value=f)
        c.number_format = fmt

    # by contractor
    _header(sm, 11, ["Contractor", "Plods", "Metres", "Cost (AUD)", "$/m", "Standby %"])
    contractors = sorted(df["contractor"].unique())
    for i, name in enumerate(contractors, start=12):
        sm.cell(row=i, column=1, value=name)
        w = f"Plods[contractor],$A{i},{window}"
        sm.cell(row=i, column=2, value=f"=COUNTIFS({w})")
        sm.cell(row=i, column=3, value=f"=SUMIFS(Plods[metres_drilled],{w})").number_format = "#,##0"
        sm.cell(row=i, column=4, value=f"=SUMIFS(Plods[cost_aud],{w})").number_format = '"$"#,##0'
        sm.cell(row=i, column=5, value=f"=IFERROR(D{i}/C{i},0)").number_format = '"$"#,##0.00'
        sm.cell(row=i, column=6, value=f"=IFERROR(SUMIFS(Plods[standby_hours],{w})/SUMIFS(Plods[hours_worked],{w}),0)").number_format = "0.0%"
    c_last = 11 + len(contractors)

    # by day (dates are values, sums are formulas)
    d0 = c_last + 3
    _header(sm, d0, ["Date", "Metres", "Cost (AUD)", "$/m"])
    days = sorted(df["plod_date"].unique())
    for i, day in enumerate(days, start=d0 + 1):
        sm.cell(row=i, column=1, value=day).number_format = "yyyy-mm-dd"
        sm.cell(row=i, column=2, value=f"=SUMIFS(Plods[metres_drilled],Plods[plod_date],$A{i})")
        sm.cell(row=i, column=3, value=f"=SUMIFS(Plods[cost_aud],Plods[plod_date],$A{i})").number_format = '"$"#,##0'
        sm.cell(row=i, column=4, value=f"=IFERROR(C{i}/B{i},0)").number_format = '"$"#,##0.00'
    d_last = d0 + len(days)
    for col, w in zip("ABCDEF", (24, 12, 14, 14, 12, 12)):
        sm.column_dimensions[col].width = w

    # native charts
    bar = BarChart()
    bar.title, bar.y_axis.title = "Metres by contractor", "metres"
    bar.add_data(Reference(sm, min_col=3, min_row=11, max_row=c_last), titles_from_data=True)
    bar.set_categories(Reference(sm, min_col=1, min_row=12, max_row=c_last))
    bar.height, bar.width = 7, 12
    sm.add_chart(bar, "H3")
    line = LineChart()
    line.title, line.y_axis.title = "Cost per metre by day", "AUD / m"
    line.add_data(Reference(sm, min_col=4, min_row=d0, max_row=d_last), titles_from_data=True)
    line.set_categories(Reference(sm, min_col=1, min_row=d0 + 1, max_row=d_last))
    line.height, line.width = 7, 18
    sm.add_chart(line, "H18")
    sm.sheet_view.showGridLines = False

    for sheet in (sm, ws):
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.fitToWidth = 1
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.fitToHeight = 0

    Path(out_path).parent.mkdir(exist_ok=True)
    wb.save(out_path)


def main(db_path="data/processed/plods.db", out="reports/plod_workbook.xlsx"):
    conn = sqlite3.connect(db_path)
    df = pd.read_sql(f"SELECT {','.join(DATA_COLS)} FROM drill_plods ORDER BY plod_date, contractor", conn)
    df["plod_date"] = pd.to_datetime(df["plod_date"])
    build(df, out)
    print(f"Wrote {out} ({len(df)} plods)")


if __name__ == "__main__":
    main(*sys.argv[1:])
