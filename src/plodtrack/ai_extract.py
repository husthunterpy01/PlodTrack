"""Optional: pull structured plod fields out of a free-text shift report with Claude.

The model output is NEVER trusted blindly: it is parsed as JSON, validated against the same
rules as the Excel ingest, and anything that fails goes to a human review list.
Requires ANTHROPIC_API_KEY or GROQ_API_KEY. Usage: python -m plodtrack.ai_extract "report text..."
"""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime

FIELDS = {"plod_date": "YYYY-MM-DD", "shift": "DAY|NIGHT", "rig_id": "string", "hole_id": "string",
          "drill_type": "RC|DD|AC", "metres_drilled": "number", "hours_worked": "number",
          "standby_hours": "number", "cost_aud": "number or null"}


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate(rec):
    """Same rules as the Excel ingest (ingest.clean). Returns the list of failing fields."""
    if not isinstance(rec, dict):
        return ["not_an_object"]
    errs = []
    try:
        datetime.strptime(str(rec.get("plod_date")), "%Y-%m-%d")
    except ValueError:
        errs.append("plod_date")
    if rec.get("shift") not in ("DAY", "NIGHT"): errs.append("shift")
    if rec.get("drill_type") not in ("RC", "DD", "AC"): errs.append("drill_type")
    for k in ("rig_id", "hole_id"):
        if not isinstance(rec.get(k), str) or not rec[k].strip(): errs.append(k)
    if not _num(rec.get("metres_drilled")) or rec["metres_drilled"] < 0: errs.append("metres_drilled")
    if not _num(rec.get("hours_worked")) or rec["hours_worked"] <= 0: errs.append("hours_worked")
    if rec.get("standby_hours") is not None and (not _num(rec["standby_hours"]) or rec["standby_hours"] < 0):
        errs.append("standby_hours")
    if rec.get("cost_aud") is not None and (not _num(rec["cost_aud"]) or rec["cost_aud"] < 0):
        errs.append("cost_aud")
    return errs


def ground(rec, text):
    """Fields whose extracted value does not literally appear in the source text (guessed or normalised)."""
    low = text.lower()
    bad = []
    for k in ("rig_id", "hole_id", "shift", "drill_type"):
        if isinstance(rec.get(k), str) and rec[k].lower() not in low:
            bad.append(f"ungrounded:{k}")
    for k in ("metres_drilled", "hours_worked", "standby_hours", "cost_aud"):
        v = rec.get(k)
        if _num(v) and v != 0 and not any(f in text for f in {f"{v:g}", f"{v:.2f}", f"{v:,.2f}", f"{v:,.0f}"}):
            bad.append(f"ungrounded:{k}")
    return bad


def parse_json(text):
    """Tolerate code fences or a sentence around the JSON; return None if no object can be parsed."""
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None


PROMPT = ("Extract one drill plod from the report below. Reply with ONLY a JSON object with keys "
          "{fields}. Use null for anything not stated; do not guess. Shift is DAY or NIGHT (any capitalisation); "
          "use null for other wording such as evening. Drill type is RC (reverse circulation), DD (diamond) or "
          "AC (aircore); use null if it is not stated.\n\n<report>{text}</report>")


def _complete_anthropic(prompt, model):
    import anthropic
    msg = anthropic.Anthropic().messages.create(model=model or "claude-sonnet-5-5", max_tokens=500,
                                                messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text


def _complete_groq(prompt, model):
    """Groq's OpenAI-compatible endpoint; plain urllib so no extra dependency. Key from GROQ_API_KEY."""
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps({"model": model or "openai/gpt-oss-120b", "temperature": 0,
                         "messages": [{"role": "user", "content": prompt}]}).encode(),
        headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}", "Content-Type": "application/json",
                 "User-Agent": "plodtrack/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def extract(text, model=None, provider=None):
    """provider: 'anthropic' or 'groq'. Default: groq if GROQ_API_KEY is set and no ANTHROPIC_API_KEY."""
    provider = provider or ("groq" if os.environ.get("GROQ_API_KEY") and not os.environ.get("ANTHROPIC_API_KEY")
                            else "anthropic")
    prompt = PROMPT.format(fields=json.dumps(FIELDS), text=text)
    raw = (_complete_groq if provider == "groq" else _complete_anthropic)(prompt, model)
    rec = parse_json(raw)
    if rec is None:  # never crash or guess: send unparseable output to a human
        return {"record": None, "raw": raw, "needs_review": ["unparseable_output"]}
    review = validate(rec)
    if not review:  # only ground-check records that are otherwise well-formed
        review = ground(rec, text)
    return {"record": rec, "needs_review": review}


if __name__ == "__main__":
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("GROQ_API_KEY")):
        sys.exit("Set ANTHROPIC_API_KEY or GROQ_API_KEY first")
    print(json.dumps(extract(" ".join(sys.argv[1:])), indent=2))
