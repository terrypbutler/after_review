from datetime import date
from html import escape

import streamlit as st
from config import REACTION_MODEL
from modules.app_secrets import get_secret
from modules import gemini_client as genai
from modules.photo_utils import display_student_photo
from modules.seating_plan_store import (
    build_printable_plan_html,
    export_plan_filename,
    load_persisted_plan,
    plan_export_json,
    printable_plan_filename,
    save_persisted_plan,
)
from modules.seating_plan_utils import (
    DEFAULT_RATIONALE,
    DEFAULT_ZONES,
    LAYOUT_GROUPS,
    LAYOUT_HORSESHOE,
    LAYOUT_ROWS,
    class_seating_key,
    ensure_suggested_plan,
    find_pupil_seat,
    mentor_evidence_summary,
    place_or_swap_pupil,
    pupil_context_flags,
    remove_pupil_from_plan,
    seating_group_explanations,
    seating_plan_checks,
    suggested_seat_map,
    swap_seated_pupils,
    unseated_pupil_names,
)

def get_flexible_text(row, possible_names):
    """Extracts text flexibly handling variations in column names."""
    row_keys = {str(k).strip().lower(): k for k in row.keys()}
    for name in possible_names:
        clean_name = name.lower().strip()
        if clean_name in row_keys:
            val = str(row[row_keys[clean_name]]).strip()
            if val and val.upper() not in ["NAN", "N/A", "NONE", "NULL", ""]:
                if val.endswith(".0"): val = val[:-2]
                return val
    return None

def get_student_dots(student_name, df):
    """Helper function to calculate the red/green/blue dots for a given student."""
    ignore_list = ["N/A", "NONE", "NO", "N", "", "FALSE", "NAN", "0", "0.0"]
    try:
        student_row = df[df["Full Name"] == student_name].iloc[0]
        sen = get_flexible_text(student_row, ["SEN Status", "SEND Status"]) or ""
        pp = get_flexible_text(student_row, ["Disadvantaged (PP)", "PP"]) or ""
        eal = get_flexible_text(student_row, ["EAL", "EAL Status"]) or ""
        
        dots = []
        if sen.upper() not in ignore_list: dots.append("🔴")
        if eal.upper() not in ignore_list: dots.append("🟢")
        if pp.upper() not in ignore_list: dots.append("🔵")
        return " ".join(dots)
    except (KeyError, IndexError, TypeError):
        return ""

def render_seat_ui(seat_key, current_val, selected_pupil, cohort, df, plan):
    """Helper to consistently render the visual seat box without row jumping."""
    if current_val == "Empty":
        # FIXED HEIGHT PLACEHOLDER
        st.markdown("""
            <div style='height: 190px; display: flex; align-items: center; justify-content: center; 
                        border: 2px dashed #ccc; border-radius: 8px; margin-bottom: 10px; 
                        background: #fdfdfd; color: #aaa; font-size: 14px;'>
                <em>Empty</em>
            </div>
        """, unsafe_allow_html=True)
        
        # Centered place button. A selected pupil can be placed in any empty seat.
        pad_l, btn, pad_r = st.columns([1, 4, 1])
        with btn:
            if st.button(
                "➕ Place",
                key=f"add_{seat_key}",
                width="stretch",
                type="tertiary",
                disabled=not selected_pupil,
                help=(
                    f"Place {selected_pupil} here"
                    if selected_pupil
                    else "Select a pupil to place first"
                ),
            ):
                if selected_pupil:
                    place_or_swap_pupil(plan, selected_pupil, seat_key)
                    st.session_state.seats = plan["seats"]
                    st.rerun()
    else:
        # NATIVE STREAMLIT RENDERING
        display_student_photo(current_val, cohort)
        
        dots = get_student_dots(current_val, df)
        dot_html = f"<div style='display: flex; justify-content: center; width: 100%; font-size: 14px; margin: 2px 0; min-height: 20px; letter-spacing: 2px;'>{escape(dots) if dots else ''}</div>"
        st.markdown(dot_html, unsafe_allow_html=True)
        
        # The Heat-Map Routing (Now controlled by the multiselect above)
        if current_val in st.session_state.circulation_path:
            idx = st.session_state.circulation_path.index(current_val)
            total = len(st.session_state.circulation_path)
            
            # Calculate the color gradient (Dark Blue to Pale Blue)
            lightness = int(30 + (55 * (idx / (total - 1)))) if total > 1 else 30
            bg_color = f"hsl(210, 80%, {lightness}%)"
            
            # Automatically swap to dark text when the background gets light enough
            text_color = "white" if lightness < 65 else "#111111"
            
            box_style = f"background-color: {bg_color}; color: {text_color}; padding: 4px; border-radius: 6px; border: 1px solid #3498db;"
            display_name = f"{idx + 1}. {current_val}"
        else:
            box_style = "background-color: transparent; color: inherit; padding: 4px; border-radius: 6px; border: 1px solid transparent;"
            display_name = current_val
            
        st.markdown(f"<div style='text-align: center; font-size: 11px; font-weight: bold; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; margin-bottom: 8px; {box_style}'>{escape(display_name)}</div>", unsafe_allow_html=True)
        
        # A selected pupil can be moved or swapped directly into this seat.
        swap_col, remove_col = st.columns(2, gap="small")
        with swap_col:
            can_swap = bool(selected_pupil and selected_pupil != current_val)
            if st.button(
                "⇄",
                key=f"swap_into_{seat_key}",
                width="stretch",
                type="tertiary",
                disabled=not can_swap,
                help=(
                    f"Move or swap {selected_pupil} with {current_val}"
                    if can_swap
                    else "Select another pupil to move or swap"
                ),
            ):
                place_or_swap_pupil(plan, selected_pupil, seat_key)
                st.session_state.seats = plan["seats"]
                st.rerun()
        with remove_col:
            if st.button("❌", key=f"rm_{seat_key}", width="stretch", type="tertiary", help="Remove student from seat"):
                remove_pupil_from_plan(plan, current_val)
                st.session_state.seats = plan["seats"]
                st.session_state.circulation_path = plan["circulation_path"]
                st.rerun()


def _select_pupil_callback(widget_key, pupil_name):
    st.session_state[widget_key] = pupil_name


def _option_index(options, value, default=0):
    return options.index(value) if value in options else default


def render_pupil_selector_and_bank(df, plan, cohort, plan_key):
    """Render an explicit pupil selector plus a compact searchable bank."""
    all_students = [str(name).strip() for name in df["Full Name"] if str(name).strip()]
    unseated = unseated_pupil_names(plan, df)
    selector_key = f"seat_selected_pupil_{plan_key}"
    options = ["— Select a pupil —", *all_students]
    current = st.session_state.get(selector_key)
    if current not in options:
        current = unseated[0] if unseated else options[0]
        st.session_state[selector_key] = current

    selector_col, status_col = st.columns([3, 1])
    with selector_col:
        selected = st.selectbox(
            "Pupil to place, move or swap",
            options,
            key=selector_key,
            help=(
                "Type in this box to search. Select a pupil, then use Place on an "
                "empty seat or ⇄ on an occupied seat."
            ),
        )
    with status_col:
        if selected != options[0]:
            seat_key = find_pupil_seat(plan, selected)
            st.metric("Selected pupil", "Seated" if seat_key else "Unseated")
        else:
            st.metric("Unseated", len(unseated))

    with st.expander(f"👥 Unseated pupil bank ({len(unseated)})", expanded=False):
        search_col, filter_col = st.columns([2, 1])
        with search_col:
            search = st.text_input(
                "Search unseated pupils",
                key=f"seat_bank_search_{plan_key}",
                placeholder="Name…",
            ).strip().casefold()
        with filter_col:
            filters = st.multiselect(
                "Provision filters",
                ["SEND", "EAL", "PP"],
                key=f"seat_bank_filters_{plan_key}",
            )

        rows = {
            str(row["Full Name"]).strip(): row
            for _, row in df.iterrows()
            if str(row.get("Full Name", "")).strip()
        }
        visible = []
        for name in unseated:
            flags = pupil_context_flags(rows[name]) if name in rows else set()
            if search and search not in name.casefold():
                continue
            if filters and not set(filters).issubset(flags):
                continue
            visible.append((name, flags))

        if not visible:
            st.caption("No unseated pupils match those filters.")
        else:
            columns = st.columns(4, gap="small")
            for index, (name, flags) in enumerate(visible):
                with columns[index % 4]:
                    st.button(
                        name,
                        key=f"bank_choose_{plan_key}_{index}_{name}",
                        width="stretch",
                        on_click=_select_pupil_callback,
                        args=(selector_key, name),
                        help="Select this pupil for placement",
                    )
                    st.caption(" · ".join(sorted(flags)) or "No provision flag")

    return None if selected == options[0] else selected


def render_room_configuration(plan, plan_key):
    """Render the deliberately limited physical-room configuration."""
    zones = plan.setdefault("zones", DEFAULT_ZONES.copy())
    with st.expander("🏫 Classroom zones", expanded=False):
        st.caption(
            "Set where the class faces and where the teacher begins circulating."
        )
        front_col, teacher_col = st.columns(2)
        with front_col:
            zones["front_edge"] = st.selectbox(
                "Front of class / whiteboard",
                ["Top", "Bottom"],
                index=_option_index(
                    ["Top", "Bottom"], zones.get("front_edge", "Top")
                ),
                key=f"zone_front_{plan_key}",
            )
        teacher_options = [
            "Front centre",
            "Centre",
            "Back centre",
            "Left side",
            "Right side",
        ]
        with teacher_col:
            zones["teacher_start"] = st.selectbox(
                "Teacher starting position",
                teacher_options,
                index=_option_index(
                    teacher_options,
                    zones.get("teacher_start", "Front centre"),
                ),
                key=f"zone_teacher_{plan_key}",
            )


def render_table_block(table_index, selected_pupil, cohort, df, plan):
    """Render one four-seat table consistently in groups and horseshoe layouts."""
    with st.container(border=True):
        st.markdown(f"**Table {table_index + 1}**")
        seat_start = table_index * 4
        top_left, top_right = st.columns(2, gap="small")
        with top_left:
            render_seat_ui(
                f"seat_{seat_start}",
                plan["seats"].get(f"seat_{seat_start}", "Empty"),
                selected_pupil,
                cohort,
                df,
                plan,
            )
        with top_right:
            render_seat_ui(
                f"seat_{seat_start + 1}",
                plan["seats"].get(f"seat_{seat_start + 1}", "Empty"),
                selected_pupil,
                cohort,
                df,
                plan,
            )
        bottom_left, bottom_right = st.columns(2, gap="small")
        with bottom_left:
            render_seat_ui(
                f"seat_{seat_start + 2}",
                plan["seats"].get(f"seat_{seat_start + 2}", "Empty"),
                selected_pupil,
                cohort,
                df,
                plan,
            )
        with bottom_right:
            render_seat_ui(
                f"seat_{seat_start + 3}",
                plan["seats"].get(f"seat_{seat_start + 3}", "Empty"),
                selected_pupil,
                cohort,
                df,
                plan,
            )


def render_front_banner():
    st.markdown(
        """
        <div style='text-align: center; background-color: #2C3E50; color: white; padding: 8px; border-radius: 8px; margin: 14px 0 20px; font-weight: bold; letter-spacing: 3px; box-shadow: 0px 4px 6px rgba(0,0,0,0.1);'>
            👨‍🏫 FRONT OF CLASSROOM (WHITEBOARD) 👩‍🏫
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_plan_checks(checks):
    """Render the deterministic plan analysis before the AI mentor."""
    st.subheader("✅ Immediate plan checks")
    metrics = checks["metrics"]
    metric_columns = st.columns(5)
    metric_columns[0].metric("Seated", metrics["seated"])
    metric_columns[1].metric("Unseated", metrics["unseated"])
    metric_columns[2].metric(
        "Peer links",
        metrics["preferred_matches"]
        + metrics["reciprocal_matches"]
        + metrics["supportive_matches"],
    )
    metric_columns[3].metric("Pairing flags", metrics["pairing_conflicts"])
    metric_columns[4].metric("Route omissions", metrics["route_omissions"])

    for alert in checks["alerts"]:
        message = f"**{alert['title']}:** {alert['message']}"
        if alert["level"] == "error":
            st.error(message)
        elif alert["level"] == "warning":
            st.warning(message)
        elif alert["level"] == "success":
            st.success(message)
        else:
            st.info(message)


def render_group_reasons(plan, df, checks):
    """Expose why current groups may or may not be defensible."""
    st.subheader("💡 Why these pupils?")
    st.caption(
        "These explanations use recorded preferences, pairing considerations, "
        "discussion style and confidence. They are prompts, not prescriptions."
    )
    explanations = seating_group_explanations(plan, df)
    if checks.get("respected_separations"):
        st.success(
            "Recorded pairing considerations currently kept in separate groups: "
            + "; ".join(checks["respected_separations"][:6])
        )
    if not explanations:
        st.caption("Seat at least two pupils together to generate explanations.")
        return
    for group in explanations:
        with st.expander(group["label"], expanded=False):
            for reason in group["reasons"]:
                st.write(f"• {reason}")


def render_rationale_cycle(plan, plan_key):
    """Capture a plan rationale and the subsequent review cycle."""
    rationale = plan.setdefault("rationale", DEFAULT_RATIONALE.copy())
    st.subheader("📝 Seating rationale and review")
    left, right = st.columns(2)
    with left:
        rationale["layout_reason"] = st.text_area(
            "Why this layout?",
            value=rationale.get("layout_reason", ""),
            key=f"rationale_layout_{plan_key}",
        )
        rationale["intentional_placements"] = st.text_area(
            "Which three placements are most intentional?",
            value=rationale.get("intentional_placements", ""),
            key=f"rationale_placements_{plan_key}",
        )
        rationale["monitor"] = st.text_area(
            "What will you monitor?",
            value=rationale.get("monitor", ""),
            key=f"rationale_monitor_{plan_key}",
        )
    with right:
        rationale["review_date"] = st.text_input(
            "Review after lesson/date",
            value=rationale.get("review_date", ""),
            placeholder=date.today().isoformat(),
            key=f"rationale_date_{plan_key}",
        )
        rationale["review_changes"] = st.text_area(
            "What changed after observation?",
            value=rationale.get("review_changes", ""),
            height=220,
            key=f"rationale_changes_{plan_key}",
        )


def render_save_and_export(plan, plan_key, df, cohort, storage_path):
    """Render explicit server save and portable print/export actions."""
    st.subheader("💾 Save and export")
    save_col, print_col, export_col = st.columns(3)
    with save_col:
        if storage_path:
            if st.button("Save to approved store", width="stretch", type="primary"):
                if save_persisted_plan(storage_path, plan_key, plan):
                    st.success("Plan saved to the configured server-side store.")
                else:
                    st.error("The configured store could not be written.")
        else:
            st.button(
                "Save to approved store",
                width="stretch",
                disabled=True,
                help="Configure SEATING_PLAN_STORAGE_PATH in Streamlit secrets.",
            )
            st.caption("Server persistence is not configured.")
    with print_col:
        st.download_button(
            "Download printable plan",
            data=build_printable_plan_html(plan, df, cohort),
            file_name=printable_plan_filename(cohort),
            mime="text/html",
            width="stretch",
        )
    with export_col:
        st.download_button(
            "Export plan JSON",
            data=plan_export_json(plan, cohort),
            file_name=export_plan_filename(cohort),
            mime="application/json",
            width="stretch",
        )
    st.caption(
        "Exports contain pupil names and must remain inside your approved school "
        "environment. Open the HTML export and choose Print / save as PDF."
    )


def render_seating_plan(df, cohort):
    st.subheader("⚡ Visual Classroom Planner")

    # Keep a separate automatically saved plan for each exact filtered class.
    if "seating_plans" not in st.session_state:
        st.session_state.seating_plans = {}
    storage_path = get_secret("SEATING_PLAN_STORAGE_PATH")
    expected_plan_key = class_seating_key(cohort, df)
    if expected_plan_key not in st.session_state.seating_plans and storage_path:
        persisted_plan = load_persisted_plan(storage_path, expected_plan_key)
        if persisted_plan:
            st.session_state.seating_plans[expected_plan_key] = persisted_plan
    plan_key, plan, plan_created = ensure_suggested_plan(
        st.session_state.seating_plans,
        df,
        cohort,
    )

    st.session_state.seats = plan["seats"]
    st.session_state.circulation_path = plan["circulation_path"]

    if plan_created:
        st.info(
            "A relationship-aware seating suggestion has been created for this "
            "class. It is saved automatically for Academic AfL and Observe Learning."
        )
    elif storage_path and plan.get("source"):
        st.caption(f"Current plan: {plan.get('source')}")

    # Initialize remaining state.
    TOTAL_SEATS = 32
    if 'mentor_chat' not in st.session_state: st.session_state.mentor_chat = []
    
    # Configure AI
    api_key = get_secret("GEMINI_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)
    
    all_students = df["Full Name"].tolist()
    assigned_students = [
        student
        for student in st.session_state.seats.values()
        if student != "Empty" and student in all_students
    ]
    unassigned_students = [s for s in all_students if s not in assigned_students]

    # --- SIDEBAR: UNSEATED OVERVIEW ---
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 👤 Unseated overview")
    
    if unassigned_students:
        next_student = unassigned_students[0]
        with st.sidebar.container(border=True):
            display_student_photo(next_student, cohort)
            dots = get_student_dots(next_student, df)
            
            dot_html = f"<div style='display: flex; justify-content: center; width: 100%; font-size: 16px; margin: 5px 0; letter-spacing: 2px;'>{escape(dots)}</div>" if dots else "<div style='margin: 5px 0;'>&nbsp;</div>"
            st.sidebar.markdown(f"<h4 style='text-align:center; margin-top:0px; font-size: 15px;'>{escape(next_student)}</h4>{dot_html}", unsafe_allow_html=True)
            st.sidebar.caption(f"**{len(unassigned_students)}** students remaining.")
    else:
        st.sidebar.success("✅ All students seated!")
        next_student = None

    # --- MAIN PAGE: TOOLS & PATH TRACKER ---
    tools_c1, tools_c2, tools_c3 = st.columns([1.6, 1.25, 1])
    with tools_c1:
        layouts = [LAYOUT_ROWS, LAYOUT_GROUPS, LAYOUT_HORSESHOE]
        saved_layout = plan.get("layout", LAYOUT_GROUPS)
        layout_choice = st.radio(
            "Seat Grouping:",
            layouts,
            index=layouts.index(saved_layout) if saved_layout in layouts else 1,
            horizontal=True,
            label_visibility="collapsed",
            key=f"seat_layout_{plan_key}",
        )
        plan["layout"] = layout_choice
    with tools_c2:
        if st.button(
            "✨ Suggest Plan",
            width="stretch",
            help=(
                "Rebuild the room using Preferred Peers, Pairing Considerations, "
                "discussion style, confidence and independence."
            ),
        ):
            plan["seats"] = suggested_seat_map(df, total_seats=TOTAL_SEATS)
            plan["circulation_path"] = []
            plan["source"] = "Suggested from spreadsheet relationships"
            plan["cleared"] = False
            st.session_state.seats = plan["seats"]
            st.session_state.circulation_path = plan["circulation_path"]
            st.rerun()
    with tools_c3:
        if st.button("🗑️ Clear Room", width="stretch"):
            plan["seats"] = {}
            plan["circulation_path"] = []
            plan["source"] = "Cleared in Seating Plan"
            plan["cleared"] = True
            st.session_state.seats = plan["seats"]
            st.session_state.circulation_path = plan["circulation_path"]
            st.session_state.mentor_chat = []
            st.rerun()

    render_room_configuration(plan, plan_key)
    selected_pupil = render_pupil_selector_and_bank(df, plan, cohort, plan_key)

    assigned_students = [
        student
        for student in plan["seats"].values()
        if student != "Empty" and student in all_students
    ]
    with st.expander("⇄ Swap two seated pupils", expanded=False):
        first_col, second_col, action_col = st.columns([2, 2, 1])
        seated_options = list(dict.fromkeys(assigned_students))
        with first_col:
            first_swap = st.selectbox(
                "First pupil",
                ["—", *seated_options],
                key=f"swap_first_{plan_key}",
            )
        with second_col:
            second_swap = st.selectbox(
                "Second pupil",
                ["—", *seated_options],
                key=f"swap_second_{plan_key}",
            )
        with action_col:
            st.write("")
            st.write("")
            if st.button(
                "Swap",
                key=f"swap_action_{plan_key}",
                width="stretch",
                disabled=(
                    first_swap == "—"
                    or second_swap == "—"
                    or first_swap == second_swap
                ),
            ):
                if swap_seated_pupils(plan, first_swap, second_swap):
                    st.session_state.seats = plan["seats"]
                    st.rerun()

    # --- NEW: RAPID CIRCULATION ROUTE BUILDER ---
    st.markdown("---")
    if assigned_students:
        # Clean up the path list just in case someone was deleted
        safe_path = [name for name in st.session_state.circulation_path if name in assigned_students]
        
        selected_path = st.multiselect(
            "👣 Build Circulation Route (Select students in the order you will visit them):",
            options=assigned_students,
            default=safe_path,
            help="Click here to rapidly build your path without the page reloading on every click.",
            key=f"circulation_path_{plan_key}",
        )
        st.session_state.circulation_path = selected_path
        plan["circulation_path"] = selected_path
    else:
        st.caption("*Seat some students to begin building a circulation route.*")

    if plan.get("zones", {}).get("front_edge", "Top") == "Top":
        render_front_banner()
    
    # --- THE VISUAL GRID ---
    if layout_choice == LAYOUT_ROWS:
        for r in range(4):
            row_cols = st.columns(8, gap="small")
            for c in range(8):
                seat_idx = (r * 8) + c
                seat_key = f"seat_{seat_idx}"
                current_val = st.session_state.seats.get(seat_key, "Empty")
                with row_cols[c]:
                    render_seat_ui(
                        seat_key,
                        current_val,
                        selected_pupil,
                        cohort,
                        df,
                        plan,
                    )

    elif layout_choice == LAYOUT_GROUPS:
        for grp_row in range(2):
            table_cols = st.columns(4, gap="medium")
            for grp_col in range(4):
                table_idx = (grp_row * 4) + grp_col
                with table_cols[grp_col]:
                    render_table_block(
                        table_idx,
                        selected_pupil,
                        cohort,
                        df,
                        plan,
                    )
    else:
        # A simple U-shaped eight-table layout, open toward the front banner.
        horseshoe_rows = (
            {0: 0, 3: 7},
            {0: 1, 3: 6},
            {0: 2, 1: 3, 2: 4, 3: 5},
        )
        for row_index, placements in enumerate(horseshoe_rows):
            table_columns = st.columns(4, gap="medium")
            for column_index, column in enumerate(table_columns):
                with column:
                    table_index = placements.get(column_index)
                    if table_index is None:
                        st.markdown(
                            "<div style='min-height:120px'></div>",
                            unsafe_allow_html=True,
                        )
                    else:
                        render_table_block(
                            table_index,
                            selected_pupil,
                            cohort,
                            df,
                            plan,
                        )

    if plan.get("zones", {}).get("front_edge", "Top") == "Bottom":
        render_front_banner()

    checks = seating_plan_checks(plan, df)
    st.markdown("---")
    render_plan_checks(checks)
    render_group_reasons(plan, df, checks)
    render_rationale_cycle(plan, plan_key)
    render_save_and_export(plan, plan_key, df, cohort, storage_path)

    # --- AI MENTOR EVALUATION SECTION ---
    st.markdown("---")
    st.subheader("🤖 ITT Mentor: Plan Evaluation")
    
    evidence_text = mentor_evidence_summary(plan, df, checks)

    if st.button("Evaluate My Plan", type="primary"):
        if not api_key:
            st.error("API Key missing.")
            return

        with st.spinner("Your mentor is reviewing your seating plan and route..."):
            prompt = (
                "**[FICTIONAL SCENARIO FOR TEACHER TRAINING - ALL DATA IS MOCK/SYNTHETIC]**\n"
                "You are an expert ITT (Initial Teacher Training) Mentor evaluating a trainee's seating plan.\n\n"
                f"**Layout shape:** {layout_choice}\n"
                f"**Privacy-minimised plan evidence:**\n{evidence_text}\n\n"
                "Task:\n"
                "1. Briefly highlight one strength of their arrangement.\n"
                "2. Ask 1 or 2 constructive, probing questions to make them justify their choices. "
                "Use the rule-based evidence and trainee rationale rather than inventing pupil needs. "
                "Ask about monitoring, independence, inclusion or circulation where the evidence supports it.\n"
                "Keep it supportive but challenging, like a real mentor conversation. Limit your response to 4 sentences."
            )
            
            try:
                model = genai.GenerativeModel(REACTION_MODEL)
                response = model.generate_content(prompt)
                st.session_state.mentor_chat = [{"role": "assistant", "content": response.text}]
            except Exception as e:
                st.error(f"Mentor AI failed: {e}")
                
    # Render Chat
    if st.session_state.mentor_chat:
        for msg in st.session_state.mentor_chat:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])
                
        teacher_reply = st.chat_input("Justify your plan to your mentor...")
        if teacher_reply:
            st.session_state.mentor_chat.append({"role": "user", "content": teacher_reply})
            with st.chat_message("user"):
                st.write(teacher_reply)
            
            with st.spinner("Mentor is typing..."):
                chat_history = "\n".join([f"{m['role']}: {m['content']}" for m in st.session_state.mentor_chat])
                follow_up_prompt = (
                    "**[FICTIONAL SCENARIO FOR TEACHER TRAINING]**\n"
                    "You are the ITT Mentor. The trainee has just justified their seating plan.\n"
                    f"Chat History:\n{chat_history}\n\n"
                    "Acknowledge their reasoning, offer a final piece of advice on classroom management, and wish them luck with the lesson. Keep it brief."
                )
                model = genai.GenerativeModel(REACTION_MODEL)
                response = model.generate_content(follow_up_prompt)
                
                st.session_state.mentor_chat.append({"role": "assistant", "content": response.text})
                st.rerun()
