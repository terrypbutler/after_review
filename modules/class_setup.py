"""Shared class and subject setup controls for simulation tools."""

import pandas as pd
import streamlit as st

from config import SUBJECTS
from modules.data_utils import filter_exact, safe_unique


CORE_SUBJECT_SET_COLUMNS = {
    "Maths": "Maths Set",
    "English": "English Set",
    "Science": "Science Set",
}

YEAR_10_OPTION_SUBJECTS = [
    "Art",
    "Computing",
    "Design",
    "Drama",
    "Geography",
    "History",
    "Hospitality",
    "Music",
    "Photography",
    "Spanish",
    "Sport",
]


def render_class_filter(
    df: pd.DataFrame,
    cohort: str,
    key_prefix: str,
    include_option_subjects: bool = False,
) -> pd.DataFrame:
    """Filter a cohort by its recorded tutor or subject class."""
    filtered_df = df.copy()
    class_sources = {
        "Tutor group": "Form Group",
        "Maths class": "Maths Set",
        "English class": "English Set",
        "Science class": "Science Set",
    }
    available_sources = {
        label: column
        for label, column in class_sources.items()
        if safe_unique(df, column)
    }

    choices = ["Whole cohort", *available_sources]
    available_options = [
        subject
        for subject in YEAR_10_OPTION_SUBJECTS
        if subject in df.columns
        and df[subject].astype(str).str.strip().ne("").any()
    ]
    if include_option_subjects and available_options:
        choices.append("Option subject")

    cohort_key = cohort.lower().replace(" ", "_")
    filter_mode = st.sidebar.selectbox(
        "Filter by class",
        choices,
        key=f"{key_prefix}_{cohort_key}_class_filter_mode",
    )

    if filter_mode == "Whole cohort":
        st.sidebar.success(f"{len(filtered_df)} students shown")
        return filtered_df

    if filter_mode == "Option subject":
        selected_subject = st.sidebar.selectbox(
            "Option subject",
            available_options,
            key=f"{key_prefix}_{cohort_key}_option_subject",
        )
        enrolled = filtered_df[selected_subject].astype(str).str.strip().ne("")
        filtered_df = filtered_df[enrolled].copy()
    else:
        column = available_sources[filter_mode]
        classes = safe_unique(df, column)
        selected_class = st.sidebar.selectbox(
            f"Select {filter_mode.lower()}",
            classes,
            key=f"{key_prefix}_{cohort_key}_{column.lower().replace(' ', '_')}",
        )
        filtered_df = filter_exact(filtered_df, column, selected_class)

    st.sidebar.success(f"{len(filtered_df)} students in this class")
    return filtered_df


def render_subject_class_setup(
    df: pd.DataFrame,
    cohort: str,
    key_prefix: str,
    subject_label: str = "Subject",
) -> tuple[str, pd.DataFrame]:
    """Render consistent subject/group controls and return the selected class."""
    cohort_key = cohort.lower().replace(" ", "_")
    st.sidebar.subheader(f"Class setup · {cohort}")
    subject = st.sidebar.selectbox(
        subject_label,
        SUBJECTS,
        key=f"{key_prefix}_{cohort_key}_subject",
    )
    filtered_df = df.copy()

    if subject in CORE_SUBJECT_SET_COLUMNS:
        set_column = CORE_SUBJECT_SET_COLUMNS[subject]
        grouping = st.sidebar.radio(
            "Class grouping",
            [f"{subject} classes", "Mixed ability · tutor groups"],
            key=f"{key_prefix}_{cohort_key}_{subject.lower()}_grouping",
        )

        if grouping == f"{subject} classes":
            sets = safe_unique(df, set_column)
            if sets:
                selected_set = st.sidebar.selectbox(
                    f"{subject} class",
                    sets,
                    key=f"{key_prefix}_{cohort_key}_{subject.lower()}_set",
                )
                filtered_df = filter_exact(filtered_df, set_column, selected_set)
            else:
                st.sidebar.warning(
                    f"No {subject.lower()}-class data is available for this cohort."
                )
                filtered_df = filtered_df.iloc[0:0]
        else:
            forms = safe_unique(df, "Form Group")
            selected_form = st.sidebar.selectbox(
                "Tutor group",
                ["Whole cohort", *forms],
                key=f"{key_prefix}_{cohort_key}_{subject.lower()}_mixed_form",
            )
            if selected_form != "Whole cohort":
                filtered_df = filter_exact(filtered_df, "Form Group", selected_form)
    else:
        forms = safe_unique(df, "Form Group")
        selected_form = st.sidebar.selectbox(
            "Tutor group",
            ["All tutor groups", *forms],
            key=f"{key_prefix}_{cohort_key}_{subject.lower()}_form",
        )
        if selected_form != "All tutor groups":
            filtered_df = filter_exact(filtered_df, "Form Group", selected_form)

    if (
        cohort == "Year 10"
        and subject in filtered_df.columns
        and subject not in CORE_SUBJECT_SET_COLUMNS
    ):
        enrolled = filtered_df[subject].astype(str).str.strip().ne("")
        filtered_df = filtered_df[enrolled].copy()

    st.sidebar.success(f"{len(filtered_df)} students in this class")
    return subject, filtered_df
