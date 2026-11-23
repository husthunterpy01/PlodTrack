-- PlodTrack schema (SQLite)
CREATE TABLE IF NOT EXISTS drill_plods (
    plod_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file    TEXT NOT NULL,
    contractor     TEXT NOT NULL,
    plod_date      DATE NOT NULL,
    shift          TEXT NOT NULL CHECK (shift IN ('DAY','NIGHT')),
    rig_id         TEXT NOT NULL,
    hole_id        TEXT NOT NULL,
    drill_type     TEXT NOT NULL CHECK (drill_type IN ('RC','DD','AC')),
    metres_drilled REAL NOT NULL CHECK (metres_drilled >= 0),
    hours_worked   REAL NOT NULL CHECK (hours_worked > 0),
    standby_hours  REAL NOT NULL DEFAULT 0,
    cost_aud       REAL NOT NULL CHECK (cost_aud >= 0),
    UNIQUE (contractor, plod_date, shift, rig_id, hole_id)
);

CREATE TABLE IF NOT EXISTS anomalies (
    anomaly_id INTEGER PRIMARY KEY AUTOINCREMENT,
    plod_id    INTEGER NOT NULL REFERENCES drill_plods(plod_id),
    rule       TEXT NOT NULL,
    detail     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rejected_rows (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,
    row_number  INTEGER NOT NULL,
    reason      TEXT NOT NULL
);

CREATE VIEW IF NOT EXISTS v_daily_summary AS
SELECT plod_date,
       SUM(metres_drilled)                         AS metres,
       SUM(cost_aud)                               AS cost_aud,
       ROUND(SUM(cost_aud) / NULLIF(SUM(metres_drilled),0), 2) AS cost_per_metre,
       ROUND(SUM(metres_drilled) / NULLIF(SUM(hours_worked),0), 2) AS metres_per_hour
FROM drill_plods GROUP BY plod_date;

CREATE VIEW IF NOT EXISTS v_contractor_summary AS
SELECT contractor,
       COUNT(*)                                    AS plods,
       SUM(metres_drilled)                         AS metres,
       SUM(cost_aud)                               AS cost_aud,
       ROUND(SUM(cost_aud) / NULLIF(SUM(metres_drilled),0), 2) AS cost_per_metre,
       ROUND(SUM(standby_hours) * 100.0 / NULLIF(SUM(hours_worked),0), 1) AS standby_pct
FROM drill_plods GROUP BY contractor;
