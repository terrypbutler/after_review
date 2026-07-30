import streamlit as st
import pandas as pd
import altair as alt

from config import APP_NAME, COHORT_URLS
from modules.app_shell import (
    apply_app_styles,
    render_home,
    render_navigation,
    render_sidebar_footer,
    render_teacher_identity,
)
from modules.class_setup import render_class_filter, render_subject_class_setup
from modules.data_loader import DataLoadError, load_data
from modules.data_utils import count_active
from modules.report_renderers import (
    generate_printable_html,
    render_photo_grid,
    render_student_card,
    render_working_group_finder,
)

st.set_page_config(
    page_title=APP_NAME,
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_app_styles()

cohort_data = {}
load_errors = {}
for cohort_name, cohort_url in COHORT_URLS.items():
    try:
        cohort_data[cohort_name] = load_data(cohort_url)
    except DataLoadError as exc:
        cohort_data[cohort_name] = pd.DataFrame()
        load_errors[cohort_name] = str(exc)

def get_cohort_data(cohort):
    df = cohort_data[cohort]
    if df.empty:
        st.error(
            f"{cohort} data is not available right now. Refresh the cohort data "
            "from the sidebar and try again."
        )
        st.stop()
    return df


page = render_navigation()
render_teacher_identity()
render_sidebar_footer(load_data.clear)

if page == "Home":
    render_home(cohort_data, load_errors)

elif page == "Student Search":
    st.title("Student search")
    st.caption("Find a pupil quickly, then open their full context and subject report.")
    search_cohort = st.radio("Select Cohort to Search:", ["Year 7", "Year 10"], horizontal=True)
    df = get_cohort_data(search_cohort)
    st.sidebar.subheader(f"🔎 Filters ({search_cohort})")
    df = render_class_filter(
        df,
        search_cohort,
        key_prefix="search",
        include_option_subjects=search_cohort == "Year 10",
    )
    query = st.text_input(
        "Search student name",
        key="search_name",
        placeholder="Start typing a first name or surname…",
    )

    if query:
        results = df[df["Full Name"].str.contains(query, case=False, na=False)]
        st.write(f"Found {len(results)} students")
        if len(results) == 0: st.warning("No matches found.")
        for _, row in results.iterrows():
            render_student_card(
                row,
                search_cohort,
                show_projected=True,
                report_type="Detailed",
                class_df=df,
            )

elif page == "Year 7":
    df = get_cohort_data("Year 7")
    st.title("Year 7 class passports")
    st.caption("Scan the cohort, adjust the level of detail and prepare a printable view.")
    st.sidebar.subheader("🔎 Filters (Year 7)")

    filtered_df = render_class_filter(df, "Year 7", key_prefix="y7")

    st.sidebar.divider()
    report_option = st.sidebar.radio("Select Report Detail", ["Base Passport (No Details)", "Short Report (Portrait & Home Life)", "Detailed Report (All Subjects)"])
    
    mode = "None"
    if report_option == "Short Report (Portrait & Home Life)": mode = "Short"
    elif report_option == "Detailed Report (All Subjects)": mode = "Detailed"

    include_relationships = st.sidebar.toggle(
        "Include student relationships",
        value=False,
        key="y7_include_relationships",
        help=(
            "Show Preferred Peers and Pairing Considerations from the spreadsheet "
            "at the bottom of each passport and in passport downloads."
        ),
    )

    # --- THE EXPORT MENU ---
    st.sidebar.divider()
    st.sidebar.markdown("### 🖨️ Print & Export")
    
    print_selection = st.sidebar.radio(
        "Select Content to Print",
        ["Photo Grid Only", "Detailed Passports Only", "Both"]
    )
    
    html_report = generate_printable_html(
        filtered_df,
        "Year 7",
        mode,
        print_selection,
        include_relationships=include_relationships,
    )
    
    st.sidebar.download_button(
        label="Download Printable Report",
        data=html_report,
        file_name="Year7_Printable_Report.html",
        mime="text/html",
        help="Downloads a perfectly formatted file. Open it and press Ctrl+P to print!"
    )
    st.sidebar.caption("Open the downloaded file in your browser and press **Ctrl + P** for a perfect multi-page printout. *(Remember to set your printer to Landscape if printing the Photo Grid!)*")

    st.subheader(f"Showing {len(filtered_df)} Students")
    render_photo_grid(filtered_df, "Year 7", num_cols=5)
    st.divider()
    st.subheader("📄 Detailed Passports")
    for _, row in filtered_df.iterrows():
        render_student_card(
            row,
            "Year 7",
            show_projected=True,
            report_type=mode,
            class_df=filtered_df,
            show_relationships=include_relationships,
        )

elif page == "Year 10":
    df = get_cohort_data("Year 10")
    st.title("Year 10 class passports")
    st.caption("Review tutor groups, sets or option classes with the context you need.")
    st.sidebar.subheader("🔎 Filters (Year 10)")

    filtered_df = render_class_filter(
        df,
        "Year 10",
        key_prefix="y10",
        include_option_subjects=True,
    )

    st.sidebar.divider()
    report_option = st.sidebar.radio("Select Report Detail", ["Base Passport (No Details)", "Short Report (KS3 & Home Life)", "Detailed Report (All Subjects)"])
    
    mode = "None"
    if report_option == "Short Report (KS3 & Home Life)": mode = "Short"
    elif report_option == "Detailed Report (All Subjects)": mode = "Detailed"

    include_relationships = st.sidebar.toggle(
        "Include student relationships",
        value=False,
        key="y10_include_relationships",
        help=(
            "Show Preferred Peers and Pairing Considerations from the spreadsheet "
            "at the bottom of each passport and in passport downloads."
        ),
    )

    # --- THE EXPORT MENU ---
    st.sidebar.divider()
    st.sidebar.markdown("### 🖨️ Print & Export")
    
    print_selection = st.sidebar.radio(
        "Select Content to Print",
        ["Photo Grid Only", "Detailed Passports Only", "Both"]
    )
    
    html_report = generate_printable_html(
        filtered_df,
        "Year 10",
        mode,
        print_selection,
        include_relationships=include_relationships,
    )
    
    st.sidebar.download_button(
        label="Download Printable Report",
        data=html_report,
        file_name="Year10_Printable_Report.html",
        mime="text/html",
        help="Downloads a perfectly formatted file. Open it and press Ctrl+P to print!"
    )
    st.sidebar.caption("Open the downloaded file in your browser and press **Ctrl + P** for a perfect multi-page printout. *(Remember to set your printer to Landscape if printing the Photo Grid!)*")

    st.subheader(f"Showing {len(filtered_df)} Students")
    render_photo_grid(filtered_df, "Year 10", num_cols=5)
    st.divider()
    st.subheader("📄 Detailed Passports")
    for _, row in filtered_df.iterrows():
        render_student_card(
            row,
            "Year 10",
            show_projected=True,
            report_type=mode,
            class_df=filtered_df,
            show_relationships=include_relationships,
        )

elif page == "Analytics":
    st.title("Cohort analytics")
    st.caption("Filter the cohort to understand attainment and support needs at a glance.")
    analytics_cohort = st.radio("Select Cohort to Analyze:", ["Year 7", "Year 10"], horizontal=True)
    df_base = get_cohort_data(analytics_cohort)

    st.sidebar.subheader("🔎 Analytics Filters")
    df = render_class_filter(
        df_base,
        analytics_cohort,
        key_prefix="analytics",
        include_option_subjects=analytics_cohort == "Year 10",
    )

    st.subheader(f"Overview: {len(df)} Students")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Students", len(df))
    m2.metric("SEN Support", count_active(df, ["SEN Status", "SEND Status"]))
    m3.metric("EAL", count_active(df, ["EAL", "EAL Status"]))
    m4.metric("Pupil Premium", count_active(df, ["Disadvantaged (PP)", "Premium", "Disadvantaged", "Pupil Premium", "PP", "FSM", "Ever 6", "FSM6", "Pupil Premium Indicator"]))

    st.write("---")
    st.subheader("📈 KS2 / SATs Performance")
    g1, g2 = st.columns(2)
    
    ks2_bins = [80, 85, 90, 95, 100, 105, 110, 115, 121] 
    ks2_labels = ["80-84", "85-89", "90-94", "95-99", "100-104", "105-109", "110-114", "115-120"]
    
    with g1:
        math_col = next((c for c in df.columns if c.strip().lower() in ["ks2 maths", "ks2 math", "sats maths", "SATs Maths", "maths score"]), None)
        if math_col:
            st.markdown("**Maths Distribution**")
            counts = pd.cut(pd.to_numeric(df[math_col], errors='coerce').dropna(), bins=ks2_bins, labels=ks2_labels, right=False).value_counts().reindex(ks2_labels, fill_value=0)
            st.altair_chart(alt.Chart(pd.DataFrame({"Score Range": ks2_labels, "Students": counts.values})).mark_bar(color="#3157d5", cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(x=alt.X('Score Range', sort=ks2_labels, title="Scaled score"), y=alt.Y('Students', title="Students"), tooltip=["Score Range", "Students"]), width="stretch")
        else: st.caption("*(No Maths data available)*")
            
    with g2:
        read_col = next((c for c in df.columns if c.strip().lower() in ["ks2 read", "ks2 reading", "sats reading", "reading score"]), None)
        if read_col:
            st.markdown("**Reading Distribution**")
            counts = pd.cut(pd.to_numeric(df[read_col], errors='coerce').dropna(), bins=ks2_bins, labels=ks2_labels, right=False).value_counts().reindex(ks2_labels, fill_value=0)
            st.altair_chart(alt.Chart(pd.DataFrame({"Score Range": ks2_labels, "Students": counts.values})).mark_bar(color="#0f766e", cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(x=alt.X('Score Range', sort=ks2_labels, title="Scaled score"), y=alt.Y('Students', title="Students"), tooltip=["Score Range", "Students"]), width="stretch")
        else: st.caption("*(No Reading data available)*")

    st.write("---")
    st.subheader("Raw Data")
    desired_cols = ["Full Name", "Form Group", "Maths Set", "English Set", "Science Set", "DoB", "Gender", "SEN Status", "Disadvantaged (PP)", "Ethnicity", "EAL Status", "SATs Reading", "SATs Maths"] if analytics_cohort == "Year 7" else ["Full Name", "Form Group", "Maths Set", "English Set", "Science Set", "DoB", "Gender", "SEN Status", "SEND Detail", "Disadvantaged (PP)", "Ethnicity", "KS2 Read", "KS2 Maths", "EAL Status", "Eng Lang Predicted Grade", "Eng Lit Predicted Grade", "Maths Predicted Grade", "Sci 1 Predicted Grade", "Sci 2 Predicted Grade", "Art Predicted Grade", "Computing Predicted Grade", "Design Predicted Grade", "Drama Predicted Grade", "Geography Predicted Grade", "History Predicted Grade", "Hospitality Predicted Grade", "Music Predicted Grade", "Photography Predicted Grade", "Spanish Predicted Grade", "Sport Predicted Grade", "Attendance %", "Suspension days"]
    st.dataframe(df[[col for col in desired_cols if col in df.columns]], width="stretch")

elif page == "Seating Plan":
    st.title("Classroom seating planner")
    st.caption("Build a purposeful room layout and plan where your attention will go.")
    
    # 1. Select the base data
    cohort = st.radio("Select Class:", ["Year 7", "Year 10"], horizontal=True)
    df_base = get_cohort_data(cohort)
    
    # 2. Build the sidebar filters
    st.sidebar.subheader(f"🔎 Filters ({cohort})")
    filtered_df = render_class_filter(
        df_base,
        cohort,
        key_prefix="seat",
        include_option_subjects=cohort == "Year 10",
    )

    # 4. Use the same filtered spreadsheet class for group and seating choices.
    render_working_group_finder(filtered_df, cohort)
    st.divider()

    # 5. Pass the fully filtered list into the planner
    from modules.seating_planner import render_seating_plan
    render_seating_plan(filtered_df, cohort)

elif page == "Simulator":
    st.title("Virtual student roleplay")
    st.caption("Rehearse a short interaction, review the response and try one adjustment.")

    # 1. Select the base data
    cohort = st.radio("Select Class:", ["Year 7", "Year 10"], horizontal=True)
    df_base = get_cohort_data(cohort)

    # 2. Build the sidebar filters
    st.sidebar.subheader(f"🔎 Filters ({cohort})")
    filtered_df = render_class_filter(
        df_base,
        cohort,
        key_prefix="sim",
        include_option_subjects=cohort == "Year 10",
    )

    # 4. Pass the FILTERED list to the simulator
    from modules.student_simulator import render_simulator
    render_simulator(filtered_df, cohort)

elif page == "Academic AfL":
    st.title("Academic AfL")
    st.caption("Rehearse whole-class checks for understanding and responsive questioning.")
    cohort = st.radio("Select Class:", ["Year 7", "Year 10"], horizontal=True)
    df_base = get_cohort_data(cohort)
    selected_subject, filtered_df = render_subject_class_setup(
        df_base,
        cohort,
        key_prefix="afl",
        subject_label="What subject are you teaching?",
    )
    from modules.academic_responses import render_academic_responses
    render_academic_responses(filtered_df, cohort, selected_subject)

elif page == "Lesson Stress-Tester":
    st.title("Lesson stress-tester")
    st.caption("Test one lesson against this class before you teach it.")
    cohort = st.radio("Select Class:", ["Year 7", "Year 10"], horizontal=True)
    df_base = get_cohort_data(cohort)
    selected_subject, filtered_df = render_subject_class_setup(
        df_base,
        cohort,
        key_prefix="stress",
    )
    from modules.lesson_stress_tester import render_stress_tester
    render_stress_tester(filtered_df, cohort, selected_subject)

elif page == "Sequence Evaluator":
    st.title("Sequence of learning evaluator")
    st.caption(
        "Evaluate curriculum progression, lesson-to-lesson coherence and how well "
        "a class can access the whole sequence."
    )
    cohort = st.radio(
        "Select Class:",
        ["Year 7", "Year 10"],
        horizontal=True,
    )
    df_base = get_cohort_data(cohort)
    selected_subject, filtered_df = render_subject_class_setup(
        df_base,
        cohort,
        key_prefix="sequence",
    )
    from modules.sequence_learning_evaluator import render_sequence_evaluator
    render_sequence_evaluator(filtered_df, cohort, selected_subject)

elif page == "Observe Learning":
    st.title("Observe learning")
    st.caption("Circulate through a simulated class and practise noticing before intervening.")
    cohort = st.radio("Select Class:", ["Year 7", "Year 10"], horizontal=True)
    df_base = get_cohort_data(cohort)
    _, filtered_df = render_subject_class_setup(
        df_base,
        cohort,
        key_prefix="observation",
    )
    from modules.observe_learning import render_observation_room
    render_observation_room(filtered_df, cohort)
