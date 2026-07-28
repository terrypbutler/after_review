import streamlit as st
import pandas as pd
import base64
import hashlib
from html import escape
from io import BytesIO
from config import CACHE_TTL
from modules.data_utils import suggest_working_group
from modules.photo_utils import display_student_photo, get_student_photo


def escape_html(value):
    """Escape spreadsheet values before placing them in custom or exported HTML."""
    return escape(str(value), quote=True)

def get_flexible_text(row, possible_names):
    row_keys = {str(k).strip().lower(): k for k in row.keys()}
    for name in possible_names:
        clean_name = name.lower().strip()
        if clean_name in row_keys:
            val = str(row[row_keys[clean_name]]).strip()
            if val and val.upper() not in ["NAN", "N/A", "NONE", "NULL", ""]:
                if val.endswith(".0"): val = val[:-2]
                return val
    return None


def render_working_group_finder(class_df, cohort):
    """Render a visible spreadsheet-led group finder above the passports."""
    if class_df is None or class_df.empty or "Full Name" not in class_df.columns:
        return

    student_names = sorted(
        {
            str(value).strip()
            for value in class_df["Full Name"]
            if str(value).strip()
        },
        key=str.casefold,
    )
    if len(student_names) < 2:
        st.info("Show at least two students to create a working group.")
        return

    cohort_key = str(cohort).lower().replace(" ", "_")
    class_signature = hashlib.sha1(
        f"{cohort}|{'|'.join(student_names)}".encode("utf-8")
    ).hexdigest()[:12]
    group_sizes = list(range(2, min(6, len(student_names)) + 1))
    default_size = 4 if 4 in group_sizes else group_sizes[-1]

    with st.container(border=True):
        st.markdown("### 👥 Working Group Finder")
        st.caption(
            "Choose a pupil to build a suitable group from the class currently "
            "shown. The recommendation uses the published spreadsheet fields "
            "Preferred Peers, Pairing Considerations, Peer Discussion Style, "
            "Academic Confidence and Independence."
        )

        pupil_column, size_column = st.columns([2, 1])
        with pupil_column:
            pupil_name = st.selectbox(
                "Choose a pupil",
                student_names,
                key=f"working_group_student_{cohort_key}_{class_signature}",
            )
        with size_column:
            group_size = st.selectbox(
                "Number of pupils",
                group_sizes,
                index=group_sizes.index(default_size),
                key=f"working_group_size_{cohort_key}_{class_signature}",
                help="This total includes the pupil you selected.",
            )

        selected_rows = class_df[
            class_df["Full Name"].astype(str).str.strip() == pupil_name
        ]
        if selected_rows.empty:
            return
        selected_row = selected_rows.iloc[0]

        result_key = (
            f"working_group_finder_result_{cohort_key}_{class_signature}_"
            f"{hashlib.sha1(f'{pupil_name}|{group_size}'.encode('utf-8')).hexdigest()[:10]}"
        )
        if st.button(
            "Suggest suitable working group",
            type="primary",
            key=f"working_group_finder_button_{cohort_key}_{class_signature}",
            use_container_width=True,
        ):
            st.session_state[result_key] = suggest_working_group(
                selected_row,
                class_df,
                group_size=group_size,
            )

        if result_key in st.session_state:
            peers = st.session_state[result_key]
            if peers:
                st.success(
                    "**Suggested group:** "
                    + " · ".join([pupil_name, *peers])
                )
            else:
                st.warning(
                    "No compatible group is available within the class currently shown."
                )

            preferred = get_flexible_text(selected_row, ["Preferred Peers"])
            concerns = get_flexible_text(
                selected_row,
                ["Pairing Considerations"],
            )
            st.caption(
                "Spreadsheet basis for "
                f"{pupil_name} — preferred peers: {preferred or 'none recorded'}; "
                f"pairing considerations: {concerns or 'none recorded'}. "
                "A concern recorded against either pupil is always excluded."
            )


def render_student_card(
    row,
    cohort,
    show_projected=True,
    report_type="None",
    class_df=None,
    show_relationships=False,
):
    name = row.get("Full Name", "Unknown")
    
    with st.expander(f"👤 {name}"):
        left, right = st.columns([3, 1])
        
        with left:
            st.markdown(f"### {cohort} Profile")
            def get_val(keys):
                for k in keys:
                    for row_key in row.keys():
                        if str(row_key).strip().lower() == str(k).strip().lower():
                            val = str(row[row_key]).strip()
                            if val and val.upper() not in ["NAN", "N/A", "NONE", "NULL"]:
                                if val.endswith(".0"): val = val[:-2]
                                if "attendance" in str(k).lower() and "%" not in val: val = f"{val}%"
                                return val
                return ""

            info = {
                "Form Group": ["Form Tutor", "Tutor", "Form Group"],
                "Gender": ["Gender"],
                "Attendance": ["Attendance %", "Attendance"],
                "Suspensions": ["Suspension days", "Suspensions", "Suspension Days"],
                "SEN Status": ["SEN Status", "SEND Status"],
                "SEN Detail": ["SEN detail", "SEND detail"],
                "Ethnicity": ["Ethnicity"],
                "EAL": ["EAL", "EAL Status"],
                "Disadvantaged": ["Disadvantaged (PP)", "Premium", "Disadvantaged", "Pupil Premium", "PP"],
                "KS2 Reading": ["KS2 Read", "KS2 Reading", "SATs Reading"], 
                "KS2 Maths": ["KS2 Maths", "KS2 Math", "SATs Maths"]        
            }

            cols = st.columns(2)
            items = list(info.items())
            for i, (label, keys) in enumerate(items):
                value = get_val(keys)
                html_card = f"<div style='margin-bottom: 12px; line-height: 1.3;'><span style='font-size: 0.85em; opacity: 0.7;'>{escape_html(label)}</span><br><span style='font-size: 1.1em; font-weight: 600; display: inline-block; word-wrap: break-word;'>{escape_html(value)}</span></div>"
                cols[i % 2].markdown(html_card, unsafe_allow_html=True)
                
        with right:
            display_student_photo(name, cohort)

        st.divider()
        if show_projected:
            proj = get_flexible_text(row, ["Projected Grade", "Predicted Grade"])
            if proj: st.info(f"**Overall Projected Grade:** {proj}")
                
        if cohort == "Year 7" and report_type != "None":
            st.divider()
            st.markdown(f"### 📑 {report_type} Report")
            portrait = get_flexible_text(row, ["Transition Portrait", "Transition portrait", "Portrait"])
            if portrait:
                st.markdown("**Transition Portrait:**")
                st.write(portrait)
            elif report_type == "Detailed":
                st.caption("*(No Transition Portrait data found in spreadsheet)*")
                
            home_life = get_flexible_text(row, ["Home Life & Interests", "Home Life", "Home life & interests", "Interests"])
            if home_life:
                st.markdown("**Home Life & Interests:**")
                st.write(home_life)
            elif report_type == "Detailed":
                st.caption("*(No Home Life data found in spreadsheet)*")
                
            if report_type == "Detailed":
                st.markdown("**Subject Overviews:**")
                y7_subjects = ["Maths", "English", "Creative Arts", "PE", "Sciences", "Science", "Humanities"]
                available_y7 = {sub: get_flexible_text(row, [sub]) for sub in y7_subjects if get_flexible_text(row, [sub])}
                if available_y7: st.table(available_y7)

        elif cohort == "Year 10" and report_type != "None":
            st.divider()
            st.markdown(f"### 📑 {report_type} Report")
            ks3_report = get_flexible_text(row, ["Key Stage 3 Report", "KS3 Report", "Key Stage 3"])
            if ks3_report:
                st.markdown("**Key Stage 3 Report:**")
                st.write(ks3_report)
            elif report_type == "Detailed":
                st.caption("*(No Key Stage 3 Report data found in spreadsheet)*")

            home_life = get_flexible_text(row, ["Home Life & Interests", "Home Life", "Home life & interests", "Interests"])
            if home_life:
                st.markdown("**Home Life & Interests:**")
                st.write(home_life)
            elif report_type == "Detailed":
                st.caption("*(No Home Life data found in spreadsheet)*")

            if report_type == "Detailed":
                st.markdown("**Subject Overviews:**")
                subject_cols = ["Eng Lang","Eng Lit","Maths","Science","Art","Computing","Design","Drama","Geography","History","Hospitality","Music","Photography","Spanish","Sport"]
                table_data = []
                global_pred = get_flexible_text(row, ["Projected Grade", "Predicted Grade"]) or ""
                
                for sub in subject_cols:
                    grade = get_flexible_text(row, [sub])
                    if grade: 
                        if sub.lower() == "science":
                            sci1 = get_flexible_text(row, ["Sci 1 Predicted Grade", "Sci 1 Predicted"])
                            sci2 = get_flexible_text(row, ["Sci 2 Predicted Grade", "Sci 2 Predicted"])
                            if sci1 and sci2: sub_pred = f"{sci1}-{sci2}"
                            elif sci1: sub_pred = sci1
                            elif sci2: sub_pred = sci2
                            else: sub_pred = get_flexible_text(row, ["Science Predicted Grade", "Science Predicted"])
                        else:
                            sub_pred = get_flexible_text(row, [f"{sub} Predicted Grade", f"{sub} Predicted", f"Predicted {sub}"])
                        
                        table_data.append({"Subject": sub, "Current Grade": grade, "Predicted Grade": sub_pred if sub_pred else global_pred})
                
                if table_data:
                    st.table(pd.DataFrame(table_data).set_index("Subject"))

        if show_relationships:
            preferred = get_flexible_text(row, ["Preferred Peers"])
            concerns = get_flexible_text(row, ["Pairing Considerations"])
            st.divider()
            st.markdown("#### 🤝 Student relationships")
            relationship_columns = st.columns(2)
            with relationship_columns[0]:
                st.markdown("**Works well with**")
                st.write(preferred or "No preferred peers recorded.")
            with relationship_columns[1]:
                st.markdown("**Pairing considerations**")
                st.write(concerns or "No pairing concerns recorded.")


def render_photo_grid(df, cohort, num_cols=5):
    if df.empty:
        st.warning("No students found for this selection.")
        return

    ignore_list = ["N/A", "NONE", "NO", "N", "", "FALSE", "NAN", "0", "0.0"]
    sen_count, eal_count, pp_count = 0, 0, 0

    for _, row in df.iterrows():
        if (get_flexible_text(row, ["SEN Status", "SEND Status"]) or "").upper() not in ignore_list: sen_count += 1
        if (get_flexible_text(row, ["EAL", "EAL Status"]) or "").upper() not in ignore_list: eal_count += 1
        if (get_flexible_text(row, ["Disadvantaged (PP)", "Disadvantaged", "Pupil Premium", "PP"]) or "").upper() not in ignore_list: pp_count += 1

    st.markdown("### 📊 Selection Overview")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Students", len(df))
    m2.metric("SEN Support", sen_count)
    m3.metric("EAL", eal_count)
    m4.metric("Pupil Premium", pp_count)
    st.write("---") 

    for i in range(0, len(df), num_cols):
        cols = st.columns(num_cols)
        row_students = df.iloc[i : i + num_cols]
        for col, (_, row) in zip(cols, row_students.iterrows()):
            with col:
                name = row.get("Full Name", "Unknown")
                sen_status = get_flexible_text(row, ["SEN Status", "SEND Status"]) or ""
                eal_status = get_flexible_text(row, ["EAL", "EAL Status"]) or ""
                pp_status = get_flexible_text(row, ["Disadvantaged (PP)", "Disadvantaged", "Pupil Premium", "PP"]) or ""
                
                # 1. Draw the photo natively
                display_student_photo(name, cohort)
                
                # 2. Build the tags
                active_labels = []
                if sen_status.upper() not in ignore_list: active_labels.append(f"<span style='color: #D32F2F; font-weight: bold;'>{escape_html(sen_status)}</span>")
                if pp_status.upper() not in ignore_list: active_labels.append("<span style='color: #1976D2; font-weight: bold;'>PP</span>")
                if eal_status.upper() not in ignore_list: active_labels.append(f"<span style='color: #388E3C; font-weight: bold;'>EAL: {escape_html(eal_status)}</span>")
                
                # If there are no tags, use a non-breaking space to hold the height
                labels_html = "<br>".join(active_labels) if active_labels else "&nbsp;"
                
# 3. Render Name and Tags locked to the left edge to match the photo
                st.markdown(f"""
                    <div style="text-align: left; margin-top: 5px; min-height: 65px;">
                        <p style="font-size: 14px; font-weight: bold; color: #2C3E50; margin-bottom: 2px; margin-top: 0px;">
                            {escape_html(name)}
                        </p>
                        <p style="font-size: 12px; line-height: 1.4; margin-top: 0px;">
                            {labels_html}
                        </p>
                    </div>
                """, unsafe_allow_html=True)
                
        st.write("---")

# -------------------------------------------------------------------
# THE NEW PROFESSIONAL HTML EXPORT ENGINE
# -------------------------------------------------------------------
@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_image_base64(name, cohort):
    """Safely converts local images to embedded HTML format so they print perfectly."""
    image = get_student_photo(name, cohort)
    if image is None:
        return ""

    buffered = BytesIO()
    image.save(buffered, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buffered.getvalue()).decode()}"

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def generate_printable_html(
    df,
    cohort,
    report_type,
    print_selection,
    include_relationships=False,
):
    """Builds a beautiful, standalone HTML document formatted for A4 printing."""
    html = [
        "<!DOCTYPE html><html><head><meta charset='UTF-8'><title>Student Reports</title><style>",
        "body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #222; line-height: 1.4; margin: 15px; }",
        "@media print { body { -webkit-print-color-adjust: exact; print-color-adjust: exact; } .page-break { page-break-after: always; } }",
        
        "/* UPDATED CSS: Perfectly sized for 8-across in Landscape */",
        ".grid-container { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 30px; justify-content: flex-start; }",
        ".grid-item { width: 110px; text-align: center; border: 1px solid #ddd; padding: 6px; border-radius: 8px; page-break-inside: avoid; margin-bottom: 6px; }",
        ".photo { width: 100px; height: 130px; object-fit: cover; border-radius: 4px; border: 1px solid #ccc; }",
        ".photo-placeholder { width: 100px; height: 130px; background: #eee; border-radius: 4px; display: inline-block; line-height: 130px; color: #999; border: 1px solid #ccc; font-size: 11px; }",
        ".name { font-weight: bold; margin: 6px 0 4px 0; font-size: 11px; line-height: 1.1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }",
        ".tag { display: inline-block; font-size: 9px; padding: 2px 4px; border-radius: 4px; margin-bottom: 2px; font-weight: bold; }",
        
        ".tag-sen { background: #fee2e2; color: #b91c1c; } .tag-pp { background: #e0f2fe; color: #0369a1; } .tag-eal { background: #dcfce7; color: #15803d; }",
        ".card { border: 2px solid #2C3E50; border-radius: 8px; padding: 20px; margin-bottom: 30px; page-break-inside: avoid; }",
        ".header-row { display: flex; justify-content: space-between; margin-bottom: 15px; }",
        ".demo-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; width: 75%; }",
        ".metric { background: #f8f9fa; padding: 8px; border-radius: 4px; border: 1px solid #eee; }",
        ".metric-label { font-size: 11px; color: #666; text-transform: uppercase; } .metric-value { font-size: 14px; font-weight: bold; }",
        ".section-title { border-bottom: 2px solid #3498DB; padding-bottom: 4px; margin: 15px 0 10px 0; font-size: 16px; color: #2C3E50; font-weight: bold; }",
        "table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13px; }",
        "th, td { border: 1px solid #ddd; padding: 6px 10px; text-align: left; } th { background-color: #f2f2f2; }",
        "</style></head><body>"
    ]
    
    ignore_list = ["N/A", "NONE", "NO", "N", "", "FALSE", "NAN", "0", "0.0"]
    
    # --- 1. GENERATE THE PHOTO GRID (IF REQUESTED) ---
    if print_selection in ["Photo Grid Only", "Both"]:
        html.append(f"<h2>{escape_html(cohort)} - Photo Overview</h2><div class='grid-container'>")
        for _, row in df.iterrows():
            name = row.get("Full Name", "Unknown")
            img_b64 = get_image_base64(name, cohort)
            sen_status = get_flexible_text(row, ["SEN Status", "SEND Status"]) or ""
            pp_status = get_flexible_text(row, ["Disadvantaged (PP)", "PP"]) or ""
            eal_status = get_flexible_text(row, ["EAL", "EAL Status"]) or ""
            
            img_html = f"<img src='{img_b64}' class='photo'>" if img_b64 else "<div class='photo-placeholder'>No Photo</div>"
            html.append(f"<div class='grid-item'>{img_html}<div class='name'>{escape_html(name)}</div>")
            if sen_status.upper() not in ignore_list: html.append(f"<div class='tag tag-sen'>{escape_html(sen_status)}</div>")
            if pp_status.upper() not in ignore_list: html.append(f"<div class='tag tag-pp'>PP</div>")
            if eal_status.upper() not in ignore_list: html.append(f"<div class='tag tag-eal'>EAL: {escape_html(eal_status)}</div>")
            html.append("</div>")
        html.append("</div>")
        
        # Add a page break if we are printing both
        if print_selection == "Both":
            html.append("<div class='page-break'></div>")
    
    # --- 2. GENERATE THE PASSPORTS (IF REQUESTED) ---
    if print_selection in ["Detailed Passports Only", "Both"]:
        html.append(f"<h2>{escape_html(cohort)} - Detailed Passports</h2>")
        for _, row in df.iterrows():
            name = row.get("Full Name", "Unknown")
            img_b64 = get_image_base64(name, cohort)
            
            html.append(f"<div class='card'><h3 style='margin-top:0;'>{escape_html(name)}</h3><div class='header-row'><div class='demo-grid'>")
            
            info = {
                "Form Group": ["Form Tutor", "Tutor", "Form Group"], "Attendance": ["Attendance %", "Attendance"],
                "SEN Status": ["SEN Status", "SEND Status"], "SEN Detail": ["SEN detail", "SEND detail"],
                "Disadvantaged": ["Disadvantaged (PP)", "PP"], "KS2 Reading": ["KS2 Read", "KS2 Reading"], 
                "KS2 Maths": ["KS2 Maths", "KS2 Math"]
            }
            
            for label, keys in info.items():
                val = get_flexible_text(row, keys) or ""
                if "attendance" in label.lower() and val and "%" not in val: val += "%"
                html.append(f"<div class='metric'><div class='metric-label'>{escape_html(label)}</div><div class='metric-value'>{escape_html(val)}</div></div>")
                
            html.append(f"</div>") # End demo-grid
            html.append(f"<img src='{img_b64}' class='photo' style='width:120px;height:160px;'>" if img_b64 else "<div class='photo-placeholder' style='width:120px;height:160px;line-height:160px;'>No Photo</div>")
            html.append("</div>") # End header-row
            
            proj = get_flexible_text(row, ["Projected Grade", "Predicted Grade"])
            if proj: html.append(f"<div style='background:#e8f4f8; padding:8px; border-radius:4px; border:1px solid #bce8f1;'><strong>Overall Projected Grade:</strong> {escape_html(proj)}</div>")
                
            if cohort == "Year 7" and report_type != "None":
                port = get_flexible_text(row, ["Transition Portrait", "Portrait"])
                if port: html.append(f"<div class='section-title'>Transition Portrait</div><p>{escape_html(port)}</p>")
                home = get_flexible_text(row, ["Home Life & Interests", "Home Life"])
                if home: html.append(f"<div class='section-title'>Home Life & Interests</div><p>{escape_html(home)}</p>")
                if report_type == "Detailed":
                    rows = [f"<tr><td style='font-weight:bold; width:30%;'>{escape_html(s)}</td><td>{escape_html(get_flexible_text(row, [s]))}</td></tr>" for s in ["Maths", "English", "Creative Arts", "PE", "Sciences", "Science", "Humanities"] if get_flexible_text(row, [s])]
                    if rows: html.append(f"<div class='section-title'>Subject Overviews</div><table>{''.join(rows)}</table>")

            elif cohort == "Year 10" and report_type != "None":
                ks3 = get_flexible_text(row, ["Key Stage 3 Report", "KS3 Report"])
                if ks3: html.append(f"<div class='section-title'>Key Stage 3 Report</div><p>{escape_html(ks3)}</p>")
                home = get_flexible_text(row, ["Home Life & Interests", "Home Life"])
                if home: html.append(f"<div class='section-title'>Home Life & Interests</div><p>{escape_html(home)}</p>")
                if report_type == "Detailed":
                    rows = []
                    for sub in ["Eng Lang","Eng Lit","Maths","Science","Art","Computing","Design","Drama","Geography","History","Hospitality","Music","Photography","Spanish","Sport"]:
                        grade = get_flexible_text(row, [sub])
                        if grade:
                            sub_pred = get_flexible_text(row, [f"{sub} Predicted Grade"]) if sub.lower() != "science" else (get_flexible_text(row, ["Sci 1 Predicted Grade"]) or "") + ("-" + get_flexible_text(row, ["Sci 2 Predicted Grade"]) if get_flexible_text(row, ["Sci 2 Predicted Grade"]) else "")
                            rows.append(f"<tr><td style='font-weight:bold;'>{escape_html(sub)}</td><td>{escape_html(grade)}</td><td>{escape_html(sub_pred or proj or '')}</td></tr>")
                    if rows: html.append(f"<div class='section-title'>Subject Reports</div><table><tr><th>Subject</th><th>Current Grade</th><th>Predicted Grade</th></tr>{''.join(rows)}</table>")

            if include_relationships:
                preferred = get_flexible_text(row, ["Preferred Peers"])
                concerns = get_flexible_text(row, ["Pairing Considerations"])
                html.append(
                    "<div class='section-title'>Student Relationships</div>"
                    "<table>"
                    "<tr><th style='width:30%;'>Works well with</th>"
                    f"<td>{escape_html(preferred or 'No preferred peers recorded.')}</td></tr>"
                    "<tr><th>Pairing considerations</th>"
                    f"<td>{escape_html(concerns or 'No pairing concerns recorded.')}</td></tr>"
                    "</table>"
                )
            html.append("</div>") # End card
            
    html.append("</body></html>")
    return "\n".join(html)
