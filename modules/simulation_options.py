"""Session-scoped controls for adjusting virtual-pupil simulation metrics."""

from collections.abc import Mapping, MutableMapping

import pandas as pd


MIN_SCORE_FACTOR = 0.50
MAX_SCORE_FACTOR = 1.50
DEFAULT_SCORE_FACTOR = 1.00
ATTAINMENT_FACTOR_KEY = "saved_simulation_factor_attainment"
ATTAINMENT_FACTOR_COLUMN = "_Scenario Attainment Factor"
OPTIONS_STATE_VERSION_KEY = "_simulation_options_state_version"
OPTIONS_STATE_VERSION = 3

SCORE_FACTOR_KEYS = {
    "Participation Level": "saved_simulation_factor_participation",
    "Academic Confidence": "saved_simulation_factor_confidence",
    "Processing Speed": "saved_simulation_factor_processing",
    "Independence": "saved_simulation_factor_independence",
}
SCORE_WIDGET_KEYS = {
    "Participation Level": "simulation_slider_participation",
    "Academic Confidence": "simulation_slider_confidence",
    "Processing Speed": "simulation_slider_processing",
    "Independence": "simulation_slider_independence",
}
ATTAINMENT_WIDGET_KEY = "simulation_slider_attainment"


def initialise_score_options(state: MutableMapping) -> None:
    """Create persistent neutral defaults outside Streamlit widget state."""
    if state.get(OPTIONS_STATE_VERSION_KEY) != OPTIONS_STATE_VERSION:
        for state_key in SCORE_FACTOR_KEYS.values():
            state[state_key] = DEFAULT_SCORE_FACTOR
        state[ATTAINMENT_FACTOR_KEY] = DEFAULT_SCORE_FACTOR
        state[OPTIONS_STATE_VERSION_KEY] = OPTIONS_STATE_VERSION
        return

    for state_key in SCORE_FACTOR_KEYS.values():
        state.setdefault(state_key, DEFAULT_SCORE_FACTOR)
    state.setdefault(ATTAINMENT_FACTOR_KEY, DEFAULT_SCORE_FACTOR)


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


def current_attainment_factor(state: Mapping) -> float:
    """Return a safe, bounded whole-cohort attainment scenario factor."""
    try:
        factor = float(state.get(ATTAINMENT_FACTOR_KEY, DEFAULT_SCORE_FACTOR))
    except (TypeError, ValueError):
        factor = DEFAULT_SCORE_FACTOR
    return min(MAX_SCORE_FACTOR, max(MIN_SCORE_FACTOR, factor))


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


def apply_attainment_factor(df: pd.DataFrame, factor: float) -> pd.DataFrame:
    """Attach the session attainment factor without changing stored grades."""
    adjusted = df.copy(deep=True)
    try:
        safe_factor = float(factor)
    except (TypeError, ValueError):
        safe_factor = DEFAULT_SCORE_FACTOR
    adjusted[ATTAINMENT_FACTOR_COLUMN] = min(
        MAX_SCORE_FACTOR,
        max(MIN_SCORE_FACTOR, safe_factor),
    )
    return adjusted


def active_score_factor_summary(state: Mapping) -> list[str]:
    """Return compact labels for non-neutral controls."""
    factors = current_score_factors(state)
    active = [
        f"{column}: {factor:.2f}×"
        for column, factor in factors.items()
        if factor != DEFAULT_SCORE_FACTOR
    ]
    attainment_factor = current_attainment_factor(state)
    if attainment_factor != DEFAULT_SCORE_FACTOR:
        active.append(f"Attainment / answer success: {attainment_factor:.2f}×")
    return active


def _reset_score_options() -> None:
    """Reset slider-backed keys safely from a Streamlit callback."""
    import streamlit as st

    for column, state_key in SCORE_FACTOR_KEYS.items():
        st.session_state[state_key] = DEFAULT_SCORE_FACTOR
        widget_key = SCORE_WIDGET_KEYS[column]
        if widget_key in st.session_state:
            st.session_state[widget_key] = DEFAULT_SCORE_FACTOR
    st.session_state[ATTAINMENT_FACTOR_KEY] = DEFAULT_SCORE_FACTOR
    if ATTAINMENT_WIDGET_KEY in st.session_state:
        st.session_state[ATTAINMENT_WIDGET_KEY] = DEFAULT_SCORE_FACTOR


def _save_slider_value(widget_key: str, state_key: str) -> None:
    """Copy a temporary widget value into persistent session state."""
    import streamlit as st

    st.session_state[state_key] = st.session_state[widget_key]


def render_score_options() -> None:
    """Render the five simulation sliders on the Options page."""
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
            widget_key = SCORE_WIDGET_KEYS[column]
            initial_value = {}
            if widget_key not in st.session_state:
                initial_value["value"] = current_score_factors(
                    st.session_state
                )[column]
            st.slider(
                column,
                min_value=MIN_SCORE_FACTOR,
                max_value=MAX_SCORE_FACTOR,
                step=0.05,
                format="%.2f×",
                key=widget_key,
                on_change=_save_slider_value,
                args=(widget_key, state_key),
                help=(
                    f"Multiplies every pupil's {column} score for this browser "
                    "session without changing the spreadsheet."
                ),
                **initial_value,
            )

    attainment_initial_value = {}
    if ATTAINMENT_WIDGET_KEY not in st.session_state:
        attainment_initial_value["value"] = current_attainment_factor(
            st.session_state
        )
    st.slider(
        "Attainment / answer success",
        min_value=MIN_SCORE_FACTOR,
        max_value=MAX_SCORE_FACTOR,
        step=0.05,
        format="%.2f×",
        key=ATTAINMENT_WIDGET_KEY,
        on_change=_save_slider_value,
        args=(ATTAINMENT_WIDGET_KEY, ATTAINMENT_FACTOR_KEY),
        help=(
            "Adjusts how likely pupils are to produce secure or correct academic "
            "answers. Participation still controls their willingness to respond."
        ),
        **attainment_initial_value,
    )
    st.caption(
        "Below 1.00× makes partial, incorrect and uncertain answers more likely; "
        "above 1.00× makes secure answers more likely. Predicted and target grades "
        "shown in pupil records are not changed."
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
