import streamlit as st
import pandas as pd
import altair as alt

from config import APP_NAME, COHORT_URLS
from modules.app_shell import (
    apply_app_styles,
    render_home,
    render_navigation,
    render_sidebar_footer,
)
from modules.class_setup import render_subject_class_setup
from modules.data_loader import DataLoadError, load_data
from modules.data_utils import count_active, safe_unique
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
render_sidebar_footer(load_data.clear)

if page == "Home":
    render_home(cohort_data, load_errors)

elif page == "Student Search":
    st.title("Student search")
    st.caption("Find a pupil quickly, then open their full context and subject report.")
    search_cohort = st.radio("Select Cohort to Search:", ["Year 7", "Year 10"], horizontal=True)
    df = get_cohort_data(search_cohort)
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
    
    # NEW: Explicit Grouping Choice
    grouping_style = st.sidebar.radio("View Class By:", ["Mixed Ability (Tutor Groups)", "Streamed Sets (Maths)"], key="y7_group")
    
    filtered_df = df.copy()
    
    if grouping_style == "Mixed Ability (Tutor Groups)":
        available_forms = safe_unique(df, "Form Group")
        selected_form = st.sidebar.selectbox("Select Tutor Group:", ["All Tutor Groups"] + available_forms, key="y7_form")
        if selected_form != "All Tutor Groups":
            filtered_df = filtered_df[filtered_df["Form Group"].astype(str) == selected_form]
            
    else:
        available_sets = safe_unique(df, "Maths Set")
        selected_set = st.sidebar.selectbox("Select Class Set:", ["All Sets"] + available_sets, key="y7_set")
        if selected_set != "All Sets":
            filtered_df = filtered_df[filtered_df["Maths Set"].astype(str) == selected_set]

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
    
    # NEW: 3-Way Explicit Grouping Choice
    grouping_style = st.sidebar.radio("View Class By:", ["Mixed Ability (Tutor Groups)", "Streamed Sets (Maths/Science)", "Option Subject"], key="y10_group")
    
    filtered_df = df.copy()
    
    if grouping_style == "Mixed Ability (Tutor Groups)":
        available_forms = safe_unique(df, "Form Group")
        selected_form = st.sidebar.selectbox("Select Tutor Group:", ["All Tutor Groups"] + available_forms, key="y10_form")
        if selected_form != "All Tutor Groups":
            filtered_df = filtered_df[filtered_df["Form Group"].astype(str) == selected_form]
            
    elif grouping_style == "Streamed Sets (Maths/Science)":
        available_sets = safe_unique(df, "Maths Set")
        selected_set = st.sidebar.selectbox("Select Class Set:", ["All Sets"] + available_sets, key="y10_set")
        if selected_set != "All Sets":
            filtered_df = filtered_df[filtered_df["Maths Set"].astype(str) == selected_set]
            
    elif grouping_style == "Option Subject":
        available_subjects = [c for c in ["Art","Computing","Design","Drama","Geography","History","Hospitality","Music","Photography","Spanish","Sport"] if c in df.columns]
        selected_subject = st.sidebar.selectbox("Select Option Subject:", ["Select Subject..."] + available_subjects, key="y10_sub")
        if selected_subject != "Select Subject...":
            filtered_df = filtered_df[filtered_df[selected_subject].notna() & (filtered_df[selected_subject].astype(str).str.strip() != "")]

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
    selected_form = st.sidebar.multiselect("Form Tutor Group", safe_unique(df_base, "Form Group"))
    selected_math = st.sidebar.multiselect("Maths Set", safe_unique(df_base, "Maths Set"))
    available_subjects = [c for c in ["Eng Lang","Eng Lit","Maths","Science","Art","Computing","Design","Drama","Geography","History","Hospitality","Music","Photography","Spanish","Sport"] if c in df_base.columns]
    selected_subject = st.sidebar.selectbox("Option Class (optional)", ["All Subjects"] + available_subjects)

    df = df_base.copy()
    if selected_form: df = df[df["Form Group"].astype(str).isin(selected_form)]
    if selected_math: df = df[df["Maths Set"].astype(str).isin(selected_math)]
    if selected_subject != "All Subjects": df = df[df[selected_subject].notna() & (df[selected_subject].astype(str).str.strip() != "")]

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
    desired_cols = ["Full Name", "Form Group", "Maths Set", "DoB", "Gender", "SEN Status", "Disadvantaged (PP)", "Ethnicity", "EAL Status", "SATs Reading", "SATs Maths"] if analytics_cohort == "Year 7" else ["Full Name", "Form Group", "Maths Set", "DoB", "Gender", "SEN Status", "SEND Detail", "Disadvantaged (PP)", "Ethnicity", "KS2 Read", "KS2 Maths", "EAL Status", "Eng Lang Predicted Grade", "Eng Lit Predicted Grade", "Maths Predicted Grade", "Sci 1 Predicted Grade", "Sci 2 Predicted Grade", "Art Predicted Grade", "Computing Predicted Grade", "Design Predicted Grade", "Drama Predicted Grade", "Geography Predicted Grade", "History Predicted Grade", "Hospitality Predicted Grade", "Music Predicted Grade", "Photography Predicted Grade", "Spanish Predicted Grade", "Sport Predicted Grade", "Attendance %", "Suspension days"]
    st.dataframe(df[[col for col in desired_cols if col in df.columns]], width="stretch")

elif page == "Seating Plan":
    st.title("Classroom seating planner")
    st.caption("Build a purposeful room layout and plan where your attention will go.")
    
    # 1. Select the base data
    cohort = st.radio("Select Class:", ["Year 7", "Year 10"], horizontal=True)
    df_base = get_cohort_data(cohort)
    
    # 2. Build the sidebar filters
    st.sidebar.subheader(f"🔎 Filters ({cohort})")
    selected_form = st.sidebar.multiselect("Form Group (ALL by default)", safe_unique(df_base, "Form Group"), key="seat_form")
    selected_math = st.sidebar.multiselect("Maths Set (ALL by default)", safe_unique(df_base, "Maths Set"), key="seat_math")
    
    # --- NEW: Year 10 Option Class Dropdown ---
    selected_subject = "All Subjects"
    if cohort == "Year 10":
        subject_cols = [
            "Eng Lang","Eng Lit","Maths","Science","Art","Computing","Design",
            "Drama","Geography","History","Hospitality","Music","Photography",
            "Spanish","Sport"
        ]
        available_subjects = [c for c in subject_cols if c in df_base.columns]
        selected_subject = st.sidebar.selectbox("Option Class (optional)", ["All Subjects"] + available_subjects, key="seat_sub")

    # 3. Create the filtered_df
    filtered_df = df_base.copy()
    if selected_form: 
        filtered_df = filtered_df[filtered_df["Form Group"].astype(str).isin(selected_form)]
    if selected_math: 
        filtered_df = filtered_df[filtered_df["Maths Set"].astype(str).isin(selected_math)]
    
    # Apply the Subject filter if it was used
    if selected_subject != "All Subjects":
        filtered_df = filtered_df[
            filtered_df[selected_subject].notna() &
            (filtered_df[selected_subject].astype(str).str.strip() != "")
        ]

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
    selected_form = st.sidebar.multiselect("Form Group (ALL by default)", safe_unique(df_base, "Form Group"), key="sim_form")
    selected_math = st.sidebar.multiselect("Maths Set (ALL by default)", safe_unique(df_base, "Maths Set"), key="sim_math")

    # 3. Create the filtered_df
    filtered_df = df_base.copy()
    if selected_form: 
        filtered_df = filtered_df[filtered_df["Form Group"].astype(str).isin(selected_form)]
    if selected_math: 
        filtered_df = filtered_df[filtered_df["Maths Set"].astype(str).isin(selected_math)]

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
