"""Pure data helpers shared across the Streamlit pages."""

from collections.abc import Iterable

import pandas as pd

from config import COLUMN_ALIASES, COLUMNS_TO_HIDE


EMPTY_MARKERS = {"", "0", "0.0", "FALSE", "N", "N/A", "NAN", "NO", "NONE", "NULL"}


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
