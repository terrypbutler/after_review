import streamlit as st
from html import escape
from modules.helpers import get_field
from modules.photo_utils import display_student_photo


def render_student_summary(row):
    """
    Render the main summary table for a student.
    """
    summary = {
        "Form Group": get_field(row, "form_group"),
        "Gender": get_field(row, "gender"),
        "SEN Status": get_field(row, "sen_status"),
        "SEND Detail": get_field(row, "sen_detail"),
        "Ethnicity": get_field(row, "ethnicity"),
        "EAL": get_field(row, "eal"),
        "Disadvantaged": get_field(row, "pp"),
        "SATs Reading": get_field(row, "reading"),
        "SATs Maths": get_field(row, "maths")
    }

    col1, col2 = st.columns(2)
    items = list(summary.items())

    for i, (key, value) in enumerate(items):
        target = col1 if i % 2 == 0 else col2
        target.markdown(f"**{key}:** {value}")


def render_student_header(row, title, cohort="Year 7"):
    """
    Render the header section including name, DoB, and student photo.
    Left/right cropping handled automatically in photo_utils.
    """
    name = row.get("Full Name", "Unknown Student")
    dob = row.get("DoB", "")

    left, right = st.columns([3, 1])

    with left:
        if dob:
            st.markdown(f"### {title}: {name} ({dob})")
        else:
            st.markdown(f"### {title}: {name}")

    with right:
        display_student_photo(name, cohort)


def render_seating_plan_overview(plan, df, context_label="this activity"):
    """Show the saved classroom layout used by a simulation page."""
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
    seated_names = set(seats.values())
    unseated_count = max(0, len(valid_names) - len(seated_names))

    if not seats:
        st.warning(
            f"No saved seats are available for {context_label}. Open Seating Plan "
            "to create or adjust this class layout."
        )
        return

    st.success(
        f"Using the seating plan for {len(seated_names)} pupils in {context_label}."
    )
    if unseated_count:
        st.caption(
            f"{unseated_count} pupil(s) are not yet placed and will appear after "
            "the saved seats."
        )

    with st.expander("🪑 View classroom seating", expanded=False):
        st.caption(plan.get("source", "Saved in Seating Plan"))
        st.markdown(
            "<div style='text-align:center;background:#2C3E50;color:white;"
            "padding:6px;border-radius:6px;margin-bottom:12px;font-weight:bold;'>"
            "FRONT OF CLASSROOM</div>",
            unsafe_allow_html=True,
        )

        if plan.get("layout") == "Rows (4x8)":
            for row_index in range(4):
                columns = st.columns(8, gap="small")
                for column_index, column in enumerate(columns):
                    seat_index = row_index * 8 + column_index
                    name = seats.get(f"seat_{seat_index}", "Empty")
                    with column:
                        st.markdown(
                            f"<div style='min-height:58px;text-align:center;"
                            "border:1px solid #ccd3df;border-radius:6px;padding:5px;"
                            "font-size:11px;'>"
                            f"<small>Seat {seat_index + 1}</small><br>"
                            f"<strong>{escape(name)}</strong></div>",
                            unsafe_allow_html=True,
                        )
        else:
            for table_row in range(2):
                table_columns = st.columns(4, gap="small")
                for table_column, column in enumerate(table_columns):
                    table_index = table_row * 4 + table_column
                    names = [
                        seats.get(f"seat_{table_index * 4 + offset}", "Empty")
                        for offset in range(4)
                    ]
                    with column:
                        with st.container(border=True):
                            st.markdown(f"**Table {table_index + 1}**")
                            for name in names:
                                st.caption(escape(name))
