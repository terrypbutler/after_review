"""Shared class and subject setup controls for simulation tools."""

import pandas as pd
import streamlit as st

from config import SUBJECTS
from modules.data_utils import filter_exact, safe_unique


def render_subject_class_setup(
    df: pd.DataFrame,
    cohort: str,
    key_prefix: str,
    subject_label: str = "Subject",
) -> tuple[str, pd.DataFrame]:
    """Render consistent subject/group controls and return the selected class."""
    st.sidebar.subheader(f"Class setup · {cohort}")
    subject = st.sidebar.selectbox(
        subject_label,
        SUBJECTS,
        key=f"{key_prefix}_subject",
    )
    filtered_df = df.copy()

    if subject in {"Maths", "Science"}:
        grouping = st.sidebar.radio(
            "Class grouping",
            ["Streamed sets", "Mixed ability · tutor groups"],
            key=f"{key_prefix}_grouping",
        )

        if grouping == "Streamed sets":
            sets = safe_unique(df, "Maths Set")
            if sets:
                selected_set = st.sidebar.selectbox(
                    "Class set",
                    sets,
                    key=f"{key_prefix}_set",
                )
                filtered_df = filter_exact(filtered_df, "Maths Set", selected_set)
            else:
                st.sidebar.warning("No class-set data is available for this cohort.")
                filtered_df = filtered_df.iloc[0:0]
        else:
            forms = safe_unique(df, "Form Group")
            selected_form = st.sidebar.selectbox(
                "Tutor group",
                ["Whole cohort", *forms],
                key=f"{key_prefix}_mixed_form",
            )
            if selected_form != "Whole cohort":
                filtered_df = filter_exact(filtered_df, "Form Group", selected_form)
    else:
        forms = safe_unique(df, "Form Group")
        selected_form = st.sidebar.selectbox(
            "Tutor group",
            ["All tutor groups", *forms],
            key=f"{key_prefix}_form",
        )
        if selected_form != "All tutor groups":
            filtered_df = filter_exact(filtered_df, "Form Group", selected_form)

    if (
        cohort == "Year 10"
        and subject in filtered_df.columns
        and subject not in {"Maths", "Science", "English"}
    ):
        enrolled = filtered_df[subject].astype(str).str.strip().ne("")
        filtered_df = filtered_df[enrolled].copy()

    st.sidebar.success(f"{len(filtered_df)} students in this class")
    return subject, filtered_df
