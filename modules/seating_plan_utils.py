"""Shared, testable helpers for relationship-aware seating plans."""

import hashlib
from itertools import combinations
import math
import re

import pandas as pd

from modules.data_utils import suggest_working_group


TOTAL_SEATS = 32
TABLE_SIZE = 4
LAYOUT_ROWS = "Rows (4x8)"
LAYOUT_GROUPS = "Groups (8 Tables)"
LAYOUT_HORSESHOE = "Horseshoe (8 Tables)"

DEFAULT_ZONES = {
    "front_edge": "Top",
    "teacher_start": "Front centre",
}

DEFAULT_RATIONALE = {
    "layout_reason": "",
    "intentional_placements": "",
    "monitor": "",
    "review_date": "",
    "review_changes": "",
}


def class_seating_key(cohort: str, df: pd.DataFrame) -> str:
    """Return a stable key for one cohort and exact filtered class list."""
    if df is None or "Full Name" not in df.columns:
        names = []
    else:
        names = sorted(
            {
                str(value).strip()
                for value in df["Full Name"]
                if str(value).strip()
            },
            key=str.casefold,
        )
    signature = hashlib.sha1(
        f"{cohort}|{'|'.join(names)}".encode("utf-8")
    ).hexdigest()[:16]
    return f"{str(cohort).lower().replace(' ', '_')}::{signature}"


def suggested_seat_map(
    df: pd.DataFrame,
    total_seats: int = TOTAL_SEATS,
    table_size: int = TABLE_SIZE,
) -> dict[str, str]:
    """Build table groups using the spreadsheet's relationship fields."""
    if (
        df is None
        or df.empty
        or "Full Name" not in df.columns
        or total_seats < 1
        or table_size < 2
    ):
        return {}

    names = []
    seen = set()
    for value in df["Full Name"]:
        name = str(value).strip()
        key = name.casefold()
        if name and key not in seen:
            names.append(name)
            seen.add(key)

    remaining = names[:total_seats]
    seat_map = {}
    table_start = 0
    while remaining and table_start < total_seats:
        seed_name = remaining[0]
        seed_rows = df[df["Full Name"].astype(str).str.strip() == seed_name]
        if seed_rows.empty:
            remaining.pop(0)
            continue

        available = df[
            df["Full Name"].astype(str).str.strip().isin(remaining)
        ]
        peers = suggest_working_group(
            seed_rows.iloc[0],
            available,
            group_size=table_size,
        )
        group = [seed_name, *[name for name in peers if name in remaining]]

        for offset, name in enumerate(group[:table_size]):
            seat_index = table_start + offset
            if seat_index >= total_seats:
                break
            seat_map[f"seat_{seat_index}"] = name
            if name in remaining:
                remaining.remove(name)

        table_start += table_size

    return seat_map


def ensure_suggested_plan(
    plans,
    df: pd.DataFrame,
    cohort: str,
) -> tuple[str, dict, bool]:
    """Return the saved class plan, creating a suggestion when none exists."""
    key = class_seating_key(cohort, df)
    plan = plans.get(key)
    created = False

    if plan is None:
        names = (
            [
                str(value).strip()
                for value in df.get("Full Name", pd.Series(dtype=str))
                if str(value).strip()
            ]
            if df is not None
            else []
        )
        plan = {
            "cohort": cohort,
            "students": names,
            "seats": suggested_seat_map(df),
            "layout": LAYOUT_GROUPS,
            "circulation_path": [],
            "source": "Suggested from spreadsheet relationships",
            "cleared": False,
            "zones": DEFAULT_ZONES.copy(),
            "rationale": DEFAULT_RATIONALE.copy(),
        }
        plans[key] = plan
        created = True

    plan.setdefault("seats", {})
    plan.setdefault("layout", LAYOUT_GROUPS)
    plan.setdefault("circulation_path", [])
    plan.setdefault("source", "Saved in Seating Plan")
    plan.setdefault("cleared", False)
    saved_zones = plan.setdefault("zones", {})
    plan["zones"] = {
        name: saved_zones.get(name, value)
        for name, value in DEFAULT_ZONES.items()
    }
    rationale = plan.setdefault("rationale", {})
    for name, value in DEFAULT_RATIONALE.items():
        rationale.setdefault(name, value)
    return key, plan, created


def order_dataframe_by_plan(df: pd.DataFrame, plan: dict) -> pd.DataFrame:
    """Place seated pupils first in seat-number order, then append unseated pupils."""
    if df is None:
        return pd.DataFrame()
    if df.empty or "Full Name" not in df.columns:
        return df.copy()

    valid_names = {
        str(value).strip()
        for value in df["Full Name"]
        if str(value).strip()
    }

    def seat_number(item):
        try:
            return int(str(item[0]).rsplit("_", 1)[1])
        except (IndexError, ValueError):
            return TOTAL_SEATS

    seated_names = []
    seen = set()
    for _, value in sorted(plan.get("seats", {}).items(), key=seat_number):
        name = str(value).strip()
        if name in valid_names and name not in seen:
            seated_names.append(name)
            seen.add(name)

    unseated_names = [
        str(value).strip()
        for value in df["Full Name"]
        if str(value).strip() not in seen
    ]
    ordered_names = seated_names + unseated_names
    order_lookup = {name: index for index, name in enumerate(ordered_names)}

    ordered_df = df.copy()
    ordered_df["_seating_order"] = (
        ordered_df["Full Name"].astype(str).str.strip().map(order_lookup)
    )
    ordered_df = ordered_df.sort_values("_seating_order", kind="stable")
    return ordered_df.drop(columns="_seating_order")


def plan_display_columns(plan: dict) -> int:
    """Return the visual column count that matches the saved room layout."""
    return 8 if plan.get("layout") == LAYOUT_ROWS else 4


def seating_discussion_groups(
    plan: dict,
    df: pd.DataFrame,
    group_size: int,
) -> list[dict]:
    """Return adjacent pairs or four-seat groups from the saved plan."""
    if (
        df is None
        or df.empty
        or "Full Name" not in df.columns
        or group_size not in {2, 4}
    ):
        return []

    valid_names = {
        str(value).strip()
        for value in df["Full Name"]
        if str(value).strip()
    }
    seats = {
        key: str(value).strip()
        for key, value in plan.get("seats", {}).items()
        if str(value).strip() in valid_names
    }

    groups = []
    for start in range(0, TOTAL_SEATS, group_size):
        names = [
            seats.get(f"seat_{seat_index}")
            for seat_index in range(start, start + group_size)
        ]
        names = [name for name in names if name]
        if len(names) < 2:
            continue

        if plan.get("layout") in {LAYOUT_GROUPS, LAYOUT_HORSESHOE}:
            table_number = start // TABLE_SIZE + 1
            if group_size == 2:
                pair_number = (start % TABLE_SIZE) // 2 + 1
                location = f"Table {table_number} · pair {pair_number}"
            else:
                location = f"Table {table_number}"
        else:
            row_number = start // 8 + 1
            position = start % 8
            if group_size == 2:
                pair_number = position // 2 + 1
                location = f"Row {row_number} · pair {pair_number}"
            else:
                group_letter = "A" if position < 4 else "B"
                location = f"Row {row_number} · group {group_letter}"

        separator = " & " if group_size == 2 else ", "
        groups.append(
            {
                "location": location,
                "students": names,
                "label": f"{location} — {separator.join(names)}",
            }
        )

    return groups


def find_pupil_seat(plan: dict, pupil_name: str) -> str | None:
    """Return the seat occupied by ``pupil_name`` in a plan, if any."""
    target = str(pupil_name).strip().casefold()
    if not target:
        return None
    for seat_key, value in plan.get("seats", {}).items():
        if str(value).strip().casefold() == target:
            return seat_key
    return None


def place_or_swap_pupil(
    plan: dict,
    pupil_name: str,
    target_seat: str,
    total_seats: int = TOTAL_SEATS,
) -> dict:
    """Place a pupil, swapping with the target occupant when already seated."""
    pupil_name = str(pupil_name).strip()
    valid_seats = {f"seat_{index}" for index in range(total_seats)}
    if not pupil_name or target_seat not in valid_seats:
        return {"changed": False, "action": "invalid"}

    seats = plan.setdefault("seats", {})
    current_seat = find_pupil_seat(plan, pupil_name)
    target_occupant = str(seats.get(target_seat, "")).strip()
    if target_occupant.casefold() == "empty":
        target_occupant = ""

    if current_seat == target_seat:
        return {"changed": False, "action": "unchanged"}

    if current_seat:
        seats.pop(current_seat, None)
    seats[target_seat] = pupil_name

    if current_seat and target_occupant:
        seats[current_seat] = target_occupant
        action = "swapped"
    elif target_occupant:
        action = "replaced"
    else:
        action = "placed"

    plan["cleared"] = False
    plan["source"] = "Adjusted manually in Seating Plan"
    return {
        "changed": True,
        "action": action,
        "pupil": pupil_name,
        "from_seat": current_seat,
        "target_seat": target_seat,
        "other_pupil": target_occupant or None,
    }


def swap_seated_pupils(plan: dict, first_name: str, second_name: str) -> bool:
    """Swap two currently seated pupils."""
    first_seat = find_pupil_seat(plan, first_name)
    second_seat = find_pupil_seat(plan, second_name)
    if not first_seat or not second_seat or first_seat == second_seat:
        return False
    seats = plan.setdefault("seats", {})
    seats[first_seat], seats[second_seat] = seats[second_seat], seats[first_seat]
    plan["source"] = "Adjusted manually in Seating Plan"
    return True


def remove_pupil_from_plan(plan: dict, pupil_name: str) -> bool:
    """Remove a pupil from their current seat and circulation route."""
    seat_key = find_pupil_seat(plan, pupil_name)
    if not seat_key:
        return False
    plan.setdefault("seats", {}).pop(seat_key, None)
    plan["circulation_path"] = [
        name
        for name in plan.get("circulation_path", [])
        if str(name).strip().casefold() != str(pupil_name).strip().casefold()
    ]
    plan["source"] = "Adjusted manually in Seating Plan"
    return True


def unseated_pupil_names(plan: dict, df: pd.DataFrame) -> list[str]:
    """Return unseated pupils in their dataframe order."""
    if df is None or df.empty or "Full Name" not in df.columns:
        return []
    seated = {
        str(value).strip().casefold()
        for value in plan.get("seats", {}).values()
        if str(value).strip() and str(value).strip().casefold() != "empty"
    }
    return [
        str(value).strip()
        for value in df["Full Name"]
        if str(value).strip() and str(value).strip().casefold() not in seated
    ]


def _seat_number(seat_key: str) -> int | None:
    try:
        return int(str(seat_key).rsplit("_", 1)[1])
    except (IndexError, TypeError, ValueError):
        return None


def seat_coordinates(plan: dict, seat_key: str) -> tuple[float, float] | None:
    """Map a logical seat to approximate 0..1 classroom coordinates."""
    index = _seat_number(seat_key)
    if index is None or not 0 <= index < TOTAL_SEATS:
        return None

    layout = plan.get("layout", LAYOUT_GROUPS)
    if layout == LAYOUT_ROWS:
        row, column = divmod(index, 8)
        return column / 7, row / 3

    table, offset = divmod(index, TABLE_SIZE)
    seat_column = offset % 2
    seat_row = offset // 2

    if layout == LAYOUT_HORSESHOE:
        table_centres = (
            (0.06, 0.20),
            (0.06, 0.54),
            (0.16, 0.90),
            (0.39, 0.90),
            (0.61, 0.90),
            (0.84, 0.90),
            (0.94, 0.54),
            (0.94, 0.20),
        )
        centre_x, centre_y = table_centres[table]
        x = centre_x + (-0.035 if seat_column == 0 else 0.035)
        y = centre_y + (-0.035 if seat_row == 0 else 0.035)
        return max(0.0, min(1.0, x)), max(0.0, min(1.0, y))

    table_row, table_column = divmod(table, 4)
    return (table_column * 2 + seat_column) / 7, (table_row * 2 + seat_row) / 3


def seat_zone_labels(plan: dict, seat_key: str) -> list[str]:
    """Return configured classroom zones for one logical seat."""
    coordinates = seat_coordinates(plan, seat_key)
    if coordinates is None:
        return []
    x, y = coordinates
    zones = {**DEFAULT_ZONES, **plan.get("zones", {})}
    labels = []

    front_is_top = zones["front_edge"] == "Top"
    if (front_is_top and y <= 0.34) or (not front_is_top and y >= 0.66):
        labels.append("front")
    if (front_is_top and y >= 0.66) or (not front_is_top and y <= 0.34):
        labels.append("back")

    teacher_targets = {
        "Front centre": (0.5, 0.08 if front_is_top else 0.92),
        "Centre": (0.5, 0.5),
        "Back centre": (0.5, 0.92 if front_is_top else 0.08),
        "Left side": (0.08, 0.5),
        "Right side": (0.92, 0.5),
    }
    teacher_x, teacher_y = teacher_targets.get(
        zones["teacher_start"], teacher_targets["Front centre"]
    )
    if math.hypot(x - teacher_x, y - teacher_y) <= 0.30:
        labels.append("near teacher start")
    return labels


def _clean_value(value) -> str:
    text = str(value).strip()
    return "" if text.casefold() in {"", "nan", "n/a", "none", "null"} else text


def _row_value(row, possible_names) -> str:
    keys = {str(key).strip().casefold(): key for key in row.keys()}
    for possible_name in possible_names:
        source_key = keys.get(str(possible_name).strip().casefold())
        if source_key is not None:
            value = _clean_value(row[source_key])
            if value:
                return value
    return ""


def _split_names(value) -> set[str]:
    text = _clean_value(value)
    if not text:
        return set()
    return {
        name.strip().casefold()
        for name in re.split(r"[;,\n]+", text)
        if name.strip()
    }


def _is_recorded_flag(value) -> bool:
    text = _clean_value(value).casefold()
    return text not in {"", "<na>", "nat", "no", "n", "false", "0", "0.0"}


def pupil_context_flags(row) -> set[str]:
    """Return compact SEND, EAL and PP flags for a spreadsheet row."""
    flags = set()
    if _is_recorded_flag(_row_value(row, ["SEN Status", "SEND Status"])):
        flags.add("SEND")
    if _is_recorded_flag(_row_value(row, ["EAL", "EAL Status"])):
        flags.add("EAL")
    if _is_recorded_flag(_row_value(row, ["Disadvantaged (PP)", "PP"])):
        flags.add("PP")
    return flags


def _student_rows(df: pd.DataFrame) -> dict[str, object]:
    if df is None or df.empty or "Full Name" not in df.columns:
        return {}
    return {
        str(row["Full Name"]).strip().casefold(): row
        for _, row in df.iterrows()
        if str(row["Full Name"]).strip()
    }


def _discussion_style(row) -> str:
    return _row_value(row, ["Peer Discussion Style"]).casefold()


def _numeric_value(row, name: str) -> float:
    try:
        return float(_row_value(row, [name]))
    except (TypeError, ValueError):
        return 0.0


def _pair_evidence(first_name: str, second_name: str, rows: dict) -> list[str]:
    first = rows.get(first_name.casefold())
    second = rows.get(second_name.casefold())
    if first is None or second is None:
        return []

    first_key = first_name.casefold()
    second_key = second_name.casefold()
    first_preferences = _split_names(_row_value(first, ["Preferred Peers"]))
    second_preferences = _split_names(_row_value(second, ["Preferred Peers"]))
    first_concerns = _split_names(_row_value(first, ["Pairing Considerations"]))
    second_concerns = _split_names(_row_value(second, ["Pairing Considerations"]))
    reasons = []

    if second_key in first_concerns or first_key in second_concerns:
        reasons.append(f"Pairing consideration recorded for {first_name} and {second_name}")
    elif second_key in first_preferences and first_key in second_preferences:
        reasons.append(f"{first_name} and {second_name} have a reciprocal peer preference")
    elif second_key in first_preferences or first_key in second_preferences:
        reasons.append(f"A recorded peer preference links {first_name} and {second_name}")

    quiet_terms = ("quiet", "hesitant", "listener")
    supportive_terms = ("collaborative", "encouraging", "supportive")
    first_style = _discussion_style(first)
    second_style = _discussion_style(second)
    if (
        any(term in first_style for term in quiet_terms)
        and any(term in second_style for term in supportive_terms)
    ) or (
        any(term in second_style for term in quiet_terms)
        and any(term in first_style for term in supportive_terms)
    ):
        reasons.append(f"{first_name} and {second_name} may offer useful discussion balance")

    first_confidence = _numeric_value(first, "Academic Confidence")
    second_confidence = _numeric_value(second, "Academic Confidence")
    if (
        first_confidence and second_confidence
        and min(first_confidence, second_confidence) < 45
        and max(first_confidence, second_confidence) >= 50
    ):
        reasons.append(f"The pairing may balance academic confidence")
    return reasons


def seating_group_explanations(plan: dict, df: pd.DataFrame) -> list[dict]:
    """Explain recorded relationship evidence within each four-seat group."""
    rows = _student_rows(df)
    explanations = []
    for group in seating_discussion_groups(plan, df, TABLE_SIZE):
        reasons = []
        for first_name, second_name in combinations(group["students"], 2):
            reasons.extend(_pair_evidence(first_name, second_name, rows))
        reasons = list(dict.fromkeys(reasons))
        if not reasons:
            reasons = [
                "No explicit peer preference, pairing concern or discussion-balance "
                "reason is recorded for this group; add a professional rationale."
            ]
        explanations.append({**group, "reasons": reasons})
    return explanations


def _relationship_evidence(plan: dict, df: pd.DataFrame) -> dict:
    rows = _student_rows(df)
    reciprocal = []
    preferred = []
    conflicts = []
    supportive = []
    groups = seating_discussion_groups(plan, df, TABLE_SIZE)
    group_by_pupil = {}
    for group in groups:
        for name in group["students"]:
            group_by_pupil[name.casefold()] = group["location"]
        for first_name, second_name in combinations(group["students"], 2):
            first = rows.get(first_name.casefold())
            second = rows.get(second_name.casefold())
            if first is None or second is None:
                continue
            first_key = first_name.casefold()
            second_key = second_name.casefold()
            first_preferences = _split_names(_row_value(first, ["Preferred Peers"]))
            second_preferences = _split_names(_row_value(second, ["Preferred Peers"]))
            first_concerns = _split_names(_row_value(first, ["Pairing Considerations"]))
            second_concerns = _split_names(_row_value(second, ["Pairing Considerations"]))
            label = f"{first_name} + {second_name}"
            if second_key in first_concerns or first_key in second_concerns:
                conflicts.append(label)
            elif second_key in first_preferences and first_key in second_preferences:
                reciprocal.append(label)
            elif second_key in first_preferences or first_key in second_preferences:
                preferred.append(label)
            if any(
                "discussion balance" in reason
                for reason in _pair_evidence(first_name, second_name, rows)
            ):
                supportive.append(label)

    canonical_names = {
        str(row["Full Name"]).strip().casefold(): str(row["Full Name"]).strip()
        for row in rows.values()
    }
    respected_separations = []
    seen_separations = set()
    for pupil_key, row in rows.items():
        pupil_name = canonical_names[pupil_key]
        for other_key in _split_names(_row_value(row, ["Pairing Considerations"])):
            other_name = canonical_names.get(other_key)
            pair_key = tuple(sorted((pupil_key, other_key)))
            if not other_name or pair_key in seen_separations:
                continue
            seen_separations.add(pair_key)
            pupil_group = group_by_pupil.get(pupil_key)
            other_group = group_by_pupil.get(other_key)
            if pupil_group and other_group and pupil_group != other_group:
                respected_separations.append(f"{pupil_name} + {other_name}")
    return {
        "reciprocal_matches": list(dict.fromkeys(reciprocal)),
        "preferred_matches": list(dict.fromkeys(preferred)),
        "pairing_conflicts": list(dict.fromkeys(conflicts)),
        "supportive_matches": list(dict.fromkeys(supportive)),
        "respected_separations": list(dict.fromkeys(respected_separations)),
    }


def seating_plan_checks(plan: dict, df: pd.DataFrame) -> dict:
    """Return deterministic, privacy-minimised evidence about a seating plan."""
    rows = _student_rows(df)
    valid_names = {
        str(value).strip()
        for value in df.get("Full Name", [])
        if str(value).strip()
    }
    seated = {
        seat_key: str(value).strip()
        for seat_key, value in plan.get("seats", {}).items()
        if str(value).strip() in valid_names
    }
    unseated = unseated_pupil_names(plan, df)
    relationship = _relationship_evidence(plan, df)
    alerts = []

    if unseated:
        alerts.append(
            {
                "level": "info",
                "title": "Unseated pupils",
                "message": f"{len(unseated)} pupil(s) still need a seat: {', '.join(unseated[:6])}{'…' if len(unseated) > 6 else ''}",
            }
        )

    conflicts = relationship["pairing_conflicts"]
    if conflicts:
        alerts.append(
            {
                "level": "error",
                "title": "Pairing consideration",
                "message": "Review these recorded combinations: " + "; ".join(conflicts[:5]),
            }
        )

    positive_matches = (
        relationship["reciprocal_matches"]
        + relationship["preferred_matches"]
        + relationship["supportive_matches"]
    )
    if positive_matches:
        alerts.append(
            {
                "level": "success",
                "title": "Recorded peer links",
                "message": f"{len(set(positive_matches))} preferred, reciprocal or supportive link(s) sit in the same group.",
            }
        )

    priority_names = []
    for name in valid_names:
        row = rows.get(name.casefold())
        if row is not None and pupil_context_flags(row):
            priority_names.append(name)

    route_keys = {
        str(name).strip().casefold() for name in plan.get("circulation_path", [])
    }
    priority_seated = [name for name in seated.values() if name in priority_names]
    route_omissions = [
        name for name in priority_seated if name.casefold() not in route_keys
    ]
    if priority_seated and route_omissions:
        alerts.append(
            {
                "level": "warning",
                "title": "Circulation coverage",
                "message": f"{len(route_omissions)} seated SEND/EAL/PP pupil(s) are not in the planned route: {', '.join(route_omissions[:6])}{'…' if len(route_omissions) > 6 else ''}",
            }
        )

    group_distribution = []
    concentrated_groups = []
    for group in seating_discussion_groups(plan, df, TABLE_SIZE):
        targeted = [name for name in group["students"] if name in priority_names]
        group_distribution.append(
            {"location": group["location"], "targeted": len(targeted), "pupils": targeted}
        )
        if len(targeted) >= 3:
            concentrated_groups.append(f"{group['location']} ({len(targeted)})")
    if concentrated_groups:
        alerts.append(
            {
                "level": "warning",
                "title": "Targeted-pupil clustering",
                "message": "Three or more SEND/EAL/PP pupils are together at " + "; ".join(concentrated_groups),
            }
        )

    back_priority = [
        name
        for seat_key, name in seated.items()
        if name in priority_names and "back" in seat_zone_labels(plan, seat_key)
    ]
    if priority_seated and len(back_priority) >= 3 and (
        len(back_priority) / len(priority_seated)
    ) >= 0.5:
        alerts.append(
            {
                "level": "warning",
                "title": "Back-zone concentration",
                "message": f"{len(back_priority)} of {len(priority_seated)} seated SEND/EAL/PP pupils are in the configured back zone.",
            }
        )

    zone_distribution = {
        "front": [],
        "back": [],
        "near teacher start": [],
    }
    for seat_key, name in seated.items():
        for label in seat_zone_labels(plan, seat_key):
            if label in zone_distribution:
                zone_distribution[label].append(name)
    if not alerts:
        alerts.append(
            {
                "level": "success",
                "title": "Complete first check",
                "message": "No immediate rule-based concerns were found. Record what you will monitor in practice.",
            }
        )

    return {
        "metrics": {
            "seated": len(set(seated.values())),
            "unseated": len(unseated),
            "priority_seated": len(priority_seated),
            "route_omissions": len(route_omissions),
            "preferred_matches": len(relationship["preferred_matches"]),
            "reciprocal_matches": len(relationship["reciprocal_matches"]),
            "supportive_matches": len(relationship["supportive_matches"]),
            "pairing_conflicts": len(conflicts),
        },
        "alerts": alerts,
        "unseated": unseated,
        "priority_route_omissions": route_omissions,
        "group_distribution": group_distribution,
        "zone_distribution": zone_distribution,
        "back_priority": back_priority,
        **relationship,
    }


def rationale_summary_lines(plan: dict) -> list[str]:
    """Return the non-empty rationale and review fields as labelled lines."""
    rationale = {**DEFAULT_RATIONALE, **plan.get("rationale", {})}
    labels = {
        "layout_reason": "Why this layout",
        "intentional_placements": "Intentional placements",
        "monitor": "What to monitor",
        "review_date": "Review date",
        "review_changes": "What changed after review",
    }
    return [
        f"{labels[key]}: {_clean_value(rationale.get(key, ''))}"
        for key in labels
        if _clean_value(rationale.get(key, ""))
    ]


def mentor_evidence_summary(plan: dict, df: pd.DataFrame, checks: dict | None = None) -> str:
    """Build bounded structured evidence for a mentor model prompt."""
    checks = checks or seating_plan_checks(plan, df)
    metrics = checks["metrics"]
    lines = [
        f"Seated: {metrics['seated']}; unseated: {metrics['unseated']}.",
        (
            "Peer evidence: "
            f"{metrics['reciprocal_matches']} reciprocal match(es), "
            f"{metrics['preferred_matches']} one-way preferred match(es), "
            f"{metrics['supportive_matches']} discussion-balance match(es), "
            f"{metrics['pairing_conflicts']} recorded conflict(s)."
        ),
        (
            "Circulation: "
            f"{metrics['route_omissions']} seated SEND/EAL/PP pupil(s) omitted."
        ),
    ]
    if checks["respected_separations"]:
        lines.append(
            "Recorded pairing considerations kept apart: "
            f"{len(checks['respected_separations'])}."
        )
    clustered = [
        f"{item['location']}={item['targeted']}"
        for item in checks["group_distribution"]
        if item["targeted"]
    ]
    lines.append("SEND/EAL/PP distribution: " + (", ".join(clustered) or "none seated"))
    zone_distribution = checks["zone_distribution"]
    lines.append(
        "Room zones: "
        f"front={len(zone_distribution['front'])}, "
        f"back={len(zone_distribution['back'])}, "
        f"near teacher start={len(zone_distribution['near teacher start'])}."
    )
    rationale_lines = rationale_summary_lines(plan)
    names = [
        str(value).strip()
        for value in df.get("Full Name", [])
        if str(value).strip()
    ]
    for index, name in enumerate(names, start=1):
        rationale_lines = [
            re.sub(re.escape(name), f"[Pupil {index}]", line, flags=re.IGNORECASE)
            for line in rationale_lines
        ]
    lines.extend(rationale_lines)
    return "\n".join(lines)
