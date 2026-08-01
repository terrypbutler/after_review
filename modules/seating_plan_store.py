"""Opt-in persistence and privacy-conscious exports for seating plans."""

from copy import deepcopy
from html import escape
import json
from pathlib import Path
import re
import threading

import pandas as pd

from modules.seating_plan_utils import (
    LAYOUT_ROWS,
    rationale_summary_lines,
    seating_plan_checks,
)


_STORE_LOCK = threading.Lock()
_STORE_VERSION = 1


def _store_path(configured_path: str | None) -> Path | None:
    if not configured_path:
        return None
    return Path(str(configured_path).strip()).expanduser()


def _read_store(path: Path) -> dict:
    if not path.exists():
        return {"version": _STORE_VERSION, "plans": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": _STORE_VERSION, "plans": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("plans"), dict):
        return {"version": _STORE_VERSION, "plans": {}}
    return payload


def load_persisted_plan(configured_path: str | None, plan_key: str) -> dict | None:
    """Load one plan from the configured server-side store."""
    path = _store_path(configured_path)
    if path is None:
        return None
    with _STORE_LOCK:
        plan = _read_store(path).get("plans", {}).get(plan_key)
    return deepcopy(plan) if isinstance(plan, dict) else None


def save_persisted_plan(
    configured_path: str | None,
    plan_key: str,
    plan: dict,
) -> bool:
    """Atomically save one plan to an explicitly configured local store."""
    path = _store_path(configured_path)
    if path is None:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with _STORE_LOCK:
        payload = _read_store(path)
        payload["version"] = _STORE_VERSION
        payload.setdefault("plans", {})[plan_key] = deepcopy(plan)
        temporary_path = path.with_suffix(f"{path.suffix}.tmp")
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(path)
    return True


def delete_persisted_plan(configured_path: str | None, plan_key: str) -> bool:
    """Delete one saved plan without touching other classes."""
    path = _store_path(configured_path)
    if path is None or not path.exists():
        return False
    with _STORE_LOCK:
        payload = _read_store(path)
        if plan_key not in payload.get("plans", {}):
            return False
        del payload["plans"][plan_key]
        temporary_path = path.with_suffix(f"{path.suffix}.tmp")
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(path)
    return True


def plan_export_json(plan: dict, cohort: str) -> str:
    """Return a portable plan export without spreadsheet profile fields."""
    payload = {
        "version": _STORE_VERSION,
        "cohort": str(cohort),
        "layout": plan.get("layout"),
        "seats": plan.get("seats", {}),
        "circulation_path": plan.get("circulation_path", []),
        "zones": plan.get("zones", {}),
        "rationale": plan.get("rationale", {}),
        "source": plan.get("source", "Saved in Seating Plan"),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _safe_filename(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value).casefold()).strip("-") or "class"


def printable_plan_filename(cohort: str) -> str:
    return f"{_safe_filename(cohort)}-seating-plan.html"


def export_plan_filename(cohort: str) -> str:
    return f"{_safe_filename(cohort)}-seating-plan.json"


def build_printable_plan_html(plan: dict, df: pd.DataFrame, cohort: str) -> str:
    """Build a standalone, browser-printable seating plan and rationale."""
    valid_names = {
        str(value).strip()
        for value in df.get("Full Name", [])
        if str(value).strip()
    }
    seats = {
        key: str(value).strip()
        for key, value in plan.get("seats", {}).items()
        if str(value).strip() in valid_names
    }
    checks = seating_plan_checks(plan, df)
    rationale = rationale_summary_lines(plan)

    if plan.get("layout") == LAYOUT_ROWS:
        room_rows = []
        for row_index in range(4):
            cells = []
            for column_index in range(8):
                seat_index = row_index * 8 + column_index
                name = seats.get(f"seat_{seat_index}", "Empty")
                cells.append(
                    f"<td><small>Seat {seat_index + 1}</small><strong>{escape(name)}</strong></td>"
                )
            room_rows.append(f"<tr>{''.join(cells)}</tr>")
        room_html = f"<table class='rows'>{''.join(room_rows)}</table>"
    else:
        cards = []
        for table_index in range(8):
            table_names = [
                seats.get(f"seat_{table_index * 4 + offset}", "Empty")
                for offset in range(4)
            ]
            pupils = "".join(f"<li>{escape(name)}</li>" for name in table_names)
            cards.append(
                f"<section class='table-card'><h3>Table {table_index + 1}</h3><ul>{pupils}</ul></section>"
            )
        room_html = f"<div class='tables'>{''.join(cards)}</div>"

    rationale_html = "".join(f"<li>{escape(line)}</li>" for line in rationale)
    alert_html = "".join(
        f"<li><strong>{escape(alert['title'])}:</strong> {escape(alert['message'])}</li>"
        for alert in checks["alerts"]
    )
    route = " → ".join(plan.get("circulation_path", [])) or "No route recorded"
    zones = plan.get("zones", {})
    zones_html = " · ".join(
        f"{escape(str(key).replace('_', ' ').title())}: {escape(str(value))}"
        for key, value in zones.items()
    )
    front_banner = '<div class="front">FRONT OF CLASSROOM</div>'
    front_before = front_banner if zones.get("front_edge", "Top") == "Top" else ""
    front_after = front_banner if zones.get("front_edge", "Top") == "Bottom" else ""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{escape(str(cohort))} seating plan</title>
<style>
body{{font-family:Arial,sans-serif;color:#17324d;margin:28px;line-height:1.35}}
h1{{margin-bottom:4px}} .front{{background:#17324d;color:white;text-align:center;padding:8px;border-radius:6px;margin:18px 0}}
.rows{{width:100%;border-collapse:separate;border-spacing:6px}}td{{border:1px solid #b8c5d1;border-radius:6px;padding:8px;text-align:center;vertical-align:top;height:52px}}td small,td strong{{display:block}}
.tables{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.table-card{{border:1px solid #b8c5d1;border-radius:8px;padding:10px;break-inside:avoid}}.table-card h3{{margin:0 0 6px}}ul{{padding-left:20px}}
.meta{{background:#f3f6f8;border-radius:8px;padding:10px;margin:12px 0}}@media print{{body{{margin:10mm}}button{{display:none}}}}
</style>
</head>
<body>
<button onclick="window.print()">Print / save as PDF</button>
<h1>{escape(str(cohort))} seating plan</h1>
<p>{escape(str(plan.get('layout', 'Classroom layout')))}</p>
{front_before}{room_html}{front_after}
<div class="meta"><strong>Room configuration</strong><br>{zones_html or 'Not configured'}</div>
<h2>Circulation route</h2><p>{escape(route)}</p>
<h2>Rationale and review</h2><ul>{rationale_html or '<li>No rationale recorded.</li>'}</ul>
<h2>Rule-based plan checks</h2><ul>{alert_html}</ul>
</body>
</html>"""
