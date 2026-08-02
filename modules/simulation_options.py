"""Session-scoped controls for adjusting virtual-pupil simulation metrics."""

from collections.abc import Mapping, MutableMapping

import pandas as pd


MIN_SCORE_FACTOR = 0.50
MAX_SCORE_FACTOR = 1.50
DEFAULT_SCORE_FACTOR = 1.00

SCORE_FACTOR_KEYS = {
    "Participation Level": "option_factor_participation",
    "Academic Confidence": "option_factor_confidence",
    "Processing Speed": "option_factor_processing",
    "Independence": "option_factor_independence",
}


def initialise_score_options(state: MutableMapping) -> None:
    """Create neutral defaults without overwriting the current browser session."""
    for state_key in SCORE_FACTOR_KEYS.values():
        state.setdefault(state_key, DEFAULT_SCORE_FACTOR)


def current_score_factors(state: Mapping) -> dict[str, float]:
    """Return safe, bounded factors keyed by spreadsheet column name."""
    factors = {}
    for column, state_key in SCORE_FACTOR_KEYS.items():
        try:
            factor = float(state.get(state_key, DEFAULT_SCORE_FACTOR))
        except (TypeError, ValueError):
            factor = DEFAULT_SCORE_FACTOR
        factors[column] = min(MAX_SCORE_FACTOR, max(MIN_SCORE_FACTOR, factor))
    return factors


def apply_score_factors(
    df: pd.DataFrame,
    factors: Mapping[str, float],
) -> pd.DataFrame:
    """Scale selected 0–100 metrics on a copy of the cohort dataframe."""
    adjusted = df.copy(deep=True)
    for column in SCORE_FACTOR_KEYS:
        if column not in adjusted.columns:
            continue

        numeric_values = pd.to_numeric(adjusted[column], errors="coerce")
        valid_values = numeric_values.notna()
        if not valid_values.any():
            continue

        try:
            factor = float(factors.get(column, DEFAULT_SCORE_FACTOR))
        except (TypeError, ValueError):
            factor = DEFAULT_SCORE_FACTOR
        factor = min(MAX_SCORE_FACTOR, max(MIN_SCORE_FACTOR, factor))
        scaled = (numeric_values * factor).round().clip(lower=0, upper=100)
        adjusted.loc[valid_values, column] = scaled.loc[valid_values].astype(int)

    return adjusted


def active_score_factor_summary(state: Mapping) -> list[str]:
    """Return compact labels for non-neutral controls."""
    factors = current_score_factors(state)
    return [
        f"{column}: {factor:.2f}×"
        for column, factor in factors.items()
        if factor != DEFAULT_SCORE_FACTOR
    ]


def _reset_score_options() -> None:
    """Reset slider-backed keys safely from a Streamlit callback."""
    import streamlit as st

    for state_key in SCORE_FACTOR_KEYS.values():
        st.session_state[state_key] = DEFAULT_SCORE_FACTOR


def render_score_options() -> None:
    """Render the four simulation sliders on the Options page."""
    import streamlit as st

    st.subheader("Virtual pupil score scaling")
    st.write(
        "Adjust the four 0–100 simulation metrics. Values below 1.00× depress "
        "the score; values above 1.00× improve it. Adjusted scores are capped "
        "between 0 and 100."
    )

    first_row = st.columns(2)
    second_row = st.columns(2)
    controls = list(SCORE_FACTOR_KEYS.items())
    for container, (column, state_key) in zip(
        [*first_row, *second_row],
        controls,
    ):
        with container:
            st.slider(
                column,
                min_value=MIN_SCORE_FACTOR,
                max_value=MAX_SCORE_FACTOR,
                step=0.05,
                format="%.2f×",
                key=state_key,
                help=(
                    f"Multiplies every pupil's {column} score for this browser "
                    "session without changing the spreadsheet."
                ),
            )

    reset_col, note_col = st.columns([1, 3])
    with reset_col:
        st.button(
            "Reset scores to 1.00×",
            width="stretch",
            on_click=_reset_score_options,
        )
    with note_col:
        st.caption(
            "Changes affect newly generated predictions, grouping suggestions, "
            "seating checks and observation scenarios. Existing generated answers "
            "remain visible until that activity is refreshed or reset."
        )


def render_score_option_status() -> None:
    """Show active non-neutral factors in the sidebar."""
    import streamlit as st

    active = active_score_factor_summary(st.session_state)
    if not active:
        st.sidebar.caption("Virtual pupil scores: original values (1.00×)")
        return
    st.sidebar.caption("Virtual pupil scaling active:")
    for label in active:
        st.sidebar.caption(f"• {label}")
