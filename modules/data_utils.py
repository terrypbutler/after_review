"""Pure data helpers shared across the Streamlit pages."""

from collections.abc import Iterable
import re

import pandas as pd

from config import COLUMN_ALIASES, COLUMNS_TO_HIDE


EMPTY_MARKERS = {"", "0", "0.0", "FALSE", "N", "N/A", "NAN", "NO", "NONE", "NULL"}

SUBJECT_REPORT_COLUMNS = {
    "art": "Creative Arts",
    "creative arts": "Creative Arts",
    "drama": "Creative Arts",
    "english": "English",
    "geography": "Humanities",
    "history": "Humanities",
    "humanities": "Humanities",
    "math": "Maths",
    "maths": "Maths",
    "pe": "PE",
    "physical education": "PE",
    "science": "Sciences",
    "sciences": "Sciences",
    "sport": "PE",
}


def _clean_profile_value(value) -> str:
    """Return compact text for a spreadsheet value."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    text = re.sub(r"\s+", " ", str(value)).strip()
    if text.upper() in EMPTY_MARKERS:
        return ""
    if text.endswith(".0"):
        text = text[:-2]
    return text


def _row_value(row, candidate_columns: Iterable[str]) -> str:
    """Read the first populated column using case-insensitive names."""
    columns = {str(column).strip().casefold(): column for column in row.keys()}
    for candidate in candidate_columns:
        column = columns.get(candidate.strip().casefold())
        if column is None:
            continue
        value = _clean_profile_value(row[column])
        if value:
            return value
    return ""


def _report_excerpt(value: str, max_chars: int = 360) -> str:
    """Keep the useful opening of a subject report without sending it all."""
    clean = _clean_profile_value(value)
    if not clean:
        return ""

    sentences = re.split(r"(?<=[.!?])\s+", clean)
    excerpt = " ".join(sentences[:2]).strip()
    if len(excerpt) <= max_chars:
        return excerpt

    shortened = excerpt[: max_chars - 1].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{shortened}…"


def get_ai_response_profile(
    row,
    cohort: str = "",
    subject: str = "",
    max_chars: int = 1400,
) -> str:
    """Return privacy-minimised context for pupil roleplay and AI answers.

    A populated spreadsheet profile is authoritative. The structured fallback
    keeps Year 10 and older data sources working while deliberately excluding
    home-life and safeguarding narrative from routine model calls.
    """
    profile = _row_value(
        row,
        ["AI Response Profile", "AI_Response_Profile", "AI response profile"],
    )

    if not profile:
        name = _row_value(row, ["Full Name", "Preferred Name"]) or "Student"
        year = _clean_profile_value(cohort) or "school pupil"
        maths_set = _row_value(row, ["Maths Set"])
        science_set = _row_value(row, ["Science Set"])
        english_set = _row_value(row, ["English Set"])
        reading = _row_value(row, ["KS2 Read", "KS2 Reading", "SATs Reading"])
        maths = _row_value(row, ["KS2 Maths", "KS2 Math", "SATs Maths"])

        parts = [f"{name} | {year}"]
        set_values = [
            f"M{maths_set}" if maths_set else "",
            f"S{science_set}" if science_set else "",
            f"E{english_set}" if english_set else "",
        ]
        if any(set_values):
            parts.append(f"Sets {'/'.join(value for value in set_values if value)}")
        if reading or maths:
            parts.append(f"KS2 R{reading or '?'}/M{maths or '?'}")

        metrics = []
        for label, columns in (
            ("participation", ["Participation Level"]),
            ("confidence", ["Academic Confidence"]),
            ("speed", ["Processing Speed"]),
            ("independence", ["Independence"]),
        ):
            value = _row_value(row, columns)
            if value:
                metrics.append(f"{label} {value}")
        if metrics:
            parts.append(f"{', '.join(metrics)}/100")

        for label, columns in (
            ("Discussion", ["Peer Discussion Style"]),
            ("Cold call", ["Cold Call Response"]),
            ("Barrier", ["Typical Learning Barrier"]),
            ("Target", ["Current Learning Target"]),
            ("Scaffold", ["Helpful Scaffold"]),
            ("EAL", ["EAL Status", "EAL"]),
        ):
            value = _row_value(row, columns)
            if value:
                parts.append(f"{label}: {value}")

        access = "; ".join(
            value
            for value in (
                _row_value(row, ["SEN Status", "SEND Status"]),
                _row_value(row, ["SEND Detail", "SEN Detail"]),
            )
            if value
        )
        if access:
            parts.append(f"Access: {access}")

        peers = _row_value(row, ["Preferred Peers"])
        pairing = _row_value(row, ["Pairing Considerations"])
        if peers:
            parts.append(f"Works with: {peers}")
        if pairing:
            parts.append(f"Pairing consideration: {pairing}")

        parts.append(
            "Calibrate vocabulary, accuracy and uncertainty to this pupil; "
            "respond as the pupil; never mention the profile or scores"
        )
        profile = " | ".join(parts)

    report_column = SUBJECT_REPORT_COLUMNS.get(_clean_profile_value(subject).casefold())
    if report_column:
        subject_evidence = _report_excerpt(_row_value(row, [report_column]))
        if subject_evidence:
            profile = (
                f"{profile} | Subject evidence ({subject}): {subject_evidence}"
            )

    if len(profile) <= max_chars:
        return profile

    shortened = profile[: max_chars - 1].rsplit(" ", 1)[0].rstrip(" ,;|:")
    return f"{shortened}…"


def _coalesce_duplicate_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Merge duplicate columns created by aliases, keeping the first real value."""
    if not df.columns.duplicated().any():
        return df

    merged = {}
    for column in dict.fromkeys(df.columns):
        matches = df.loc[:, df.columns == column].replace("", pd.NA)
        merged[column] = matches.bfill(axis=1).iloc[:, 0]
    return pd.DataFrame(merged, index=df.index)


def prepare_data(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Normalise spreadsheet columns without changing the source dataframe."""
    df = raw_df.copy()
    df.columns = [str(column).strip() for column in df.columns]
    df = df.loc[:, ~df.columns.str.match(r"^Unnamed", case=False)]

    alias_lookup = {source.casefold(): target for source, target in COLUMN_ALIASES.items()}
    df = df.rename(columns=lambda column: alias_lookup.get(column.casefold(), column))
    df = _coalesce_duplicate_columns(df)

    hidden = {column.casefold() for column in COLUMNS_TO_HIDE}
    df = df.drop(
        columns=[column for column in df.columns if column.casefold() in hidden],
        errors="ignore",
    )
    df = df.fillna("")

    if "Full Name" in df.columns:
        df["Full Name"] = (
            df["Full Name"]
            .astype(str)
            .str.replace(r"\s+", " ", regex=True)
            .str.strip()
        )

    return df


def safe_unique(df: pd.DataFrame, column: str) -> list[str]:
    """Return clean, sorted values for a column that may not exist."""
    if column not in df.columns:
        return []

    values = {
        str(value).strip()
        for value in df[column].tolist()
        if str(value).strip() and str(value).strip().upper() not in {"NAN", "NONE"}
    }
    return sorted(values, key=str.casefold)


def filter_exact(
    df: pd.DataFrame,
    column: str,
    selected: str | Iterable[str] | None,
) -> pd.DataFrame:
    """Apply a safe exact-match filter while preserving the dataframe shape."""
    if not selected:
        return df.copy()
    if column not in df.columns:
        return df.iloc[0:0].copy()

    values = [selected] if isinstance(selected, str) else list(selected)
    wanted = {str(value).strip() for value in values}
    return df[df[column].astype(str).str.strip().isin(wanted)].copy()


def count_active(df: pd.DataFrame, candidate_columns: Iterable[str]) -> int:
    """Count rows with an active flag in the first matching column."""
    columns = {str(column).strip().casefold(): column for column in df.columns}
    selected_column = next(
        (columns[name.strip().casefold()] for name in candidate_columns if name.strip().casefold() in columns),
        None,
    )
    if selected_column is None:
        return 0

    values = df[selected_column].astype(str).str.strip().str.upper()
    return int((~values.isin(EMPTY_MARKERS)).sum())
