"""Shared, testable helpers for relationship-aware seating plans."""

import hashlib

import pandas as pd

from modules.data_utils import suggest_working_group


TOTAL_SEATS = 32
TABLE_SIZE = 4


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
            "layout": "Groups (8 Tables)",
            "circulation_path": [],
            "source": "Suggested from spreadsheet relationships",
            "cleared": False,
        }
        plans[key] = plan
        created = True

    plan.setdefault("seats", {})
    plan.setdefault("layout", "Groups (8 Tables)")
    plan.setdefault("circulation_path", [])
    plan.setdefault("source", "Saved in Seating Plan")
    plan.setdefault("cleared", False)
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
    return 8 if plan.get("layout") == "Rows (4x8)" else 4


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

        if plan.get("layout") == "Groups (8 Tables)":
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
