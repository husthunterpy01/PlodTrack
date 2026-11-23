"""Optional: pull structured plod fields out of a free-text shift report with Claude.

The model output is NEVER trusted blindly: it is parsed as JSON, validated against the same
rules as the Excel ingest, and anything that fails goes to a human review list.
Requires ANTHROPIC_API_KEY. Usage: python -m plodtrack.ai_extract "report text..."
"""
import json
import os
import sys

FIELDS = {"plod_date": "YYYY-MM-DD", "shift": "DAY|NIGHT", "rig_id": "string", "hole_id": "string",
          "drill_type": "RC|DD|AC", "metres_drilled": "number", "hours_worked": "number",
          "standby_hours": "number", "cost_aud": "number or null"}


def validate(rec):
    errs = []
    if rec.get("shift") not in ("DAY", "NIGHT"): errs.append("shift")
    if rec.get("drill_type") not in ("RC", "DD", "AC"): errs.append("drill_type")
    for k in ("metres_drilled", "hours_worked"):
        if not isinstance(rec.get(k), (int, float)) or rec[k] < 0: errs.append(k)
    return errs


def extract(text, model="claude-sonnet-5-5"):
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=model, max_tokens=500,
        messages=[{"role": "user", "content":
                   "Extract one drill plod from the report below. Reply with ONLY a JSON object with keys "
                   f"{json.dumps(FIELDS)}. Use null for anything not stated; do not guess.\n\n<report>{text}</report>"}])
    rec = json.loads(msg.content[0].text)
    return {"record": rec, "needs_review": validate(rec)}


if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set ANTHROPIC_API_KEY first")
    print(json.dumps(extract(" ".join(sys.argv[1:])), indent=2))
