import streamlit as st
import random
from config import REACTION_MODEL
from modules.app_secrets import get_secret
from modules import gemini_client as genai
from modules.photo_utils import display_student_photo

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

def render_seat_ui(seat_key, current_val, next_student, cohort, df):
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
        
        # Centered Plus button
        pad_l, btn, pad_r = st.columns([1, 4, 1])
        with btn:
            if st.button("➕", key=f"add_{seat_key}", width="stretch", type="tertiary", help="Place student here"):
                if next_student:
                    st.session_state.seats[seat_key] = next_student
                    st.rerun()
    else:
        # NATIVE STREAMLIT RENDERING
        display_student_photo(current_val, cohort)
        
        dots = get_student_dots(current_val, df)
        dot_html = f"<div style='display: flex; justify-content: center; width: 100%; font-size: 14px; margin: 2px 0; min-height: 20px; letter-spacing: 2px;'>{dots if dots else ''}</div>"
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
            
        st.markdown(f"<div style='text-align: center; font-size: 11px; font-weight: bold; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; margin-bottom: 8px; {box_style}'>{display_name}</div>", unsafe_allow_html=True)
        
        # Action Button: Now ONLY the Delete button, perfectly centered
        pad_l, c1, pad_r = st.columns([1, 2, 1])
        with c1:
            if st.button("❌", key=f"rm_{seat_key}", width="stretch", type="tertiary", help="Remove student from seat"):
                st.session_state.seats[seat_key] = "Empty"
                if current_val in st.session_state.circulation_path:
                    st.session_state.circulation_path.remove(current_val)
                st.rerun()


def render_seating_plan(df, cohort):
    st.subheader("⚡ Visual Classroom Planner")
    
    # Initialize State
    TOTAL_SEATS = 32
    if 'seats' not in st.session_state: st.session_state.seats = {}
    if 'circulation_path' not in st.session_state: st.session_state.circulation_path = []
    if 'mentor_chat' not in st.session_state: st.session_state.mentor_chat = []
    
    # Configure AI
    api_key = get_secret("GEMINI_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)
    
    all_students = df["Full Name"].tolist()
    assigned_students = [s for s in st.session_state.seats.values() if s != "Empty"]
    unassigned_students = [s for s in all_students if s not in assigned_students]

    # --- SIDEBAR: NEXT UP SPOTLIGHT ---
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 👤 Up Next to Place")
    
    if unassigned_students:
        next_student = unassigned_students[0]
        with st.sidebar.container(border=True):
            display_student_photo(next_student, cohort)
            dots = get_student_dots(next_student, df)
            
            dot_html = f"<div style='display: flex; justify-content: center; width: 100%; font-size: 16px; margin: 5px 0; letter-spacing: 2px;'>{dots}</div>" if dots else "<div style='margin: 5px 0;'>&nbsp;</div>"
            st.sidebar.markdown(f"<h4 style='text-align:center; margin-top:0px; font-size: 15px;'>{next_student}</h4>{dot_html}", unsafe_allow_html=True)
            st.sidebar.caption(f"**{len(unassigned_students)}** students remaining.")
    else:
        st.sidebar.success("✅ All students seated!")
        next_student = None

    # --- MAIN PAGE: TOOLS & PATH TRACKER ---
    tools_c1, tools_c2, tools_c3 = st.columns([1.5, 1, 1])
    with tools_c1:
        layout_choice = st.radio("Seat Grouping:", ["Rows (4x8)", "Groups (8 Tables)"], horizontal=True, label_visibility="collapsed")
    with tools_c2:
        if st.button("🪄 Auto-Fill Room", width="stretch"):
            available_seats = [f"seat_{i}" for i in range(TOTAL_SEATS) if st.session_state.seats.get(f"seat_{i}", "Empty") == "Empty"]
            random.shuffle(unassigned_students)
            for i, student in enumerate(unassigned_students):
                if i < len(available_seats):
                    st.session_state.seats[available_seats[i]] = student
            st.rerun()
    with tools_c3:
        if st.button("🗑️ Clear Room", width="stretch"):
            st.session_state.seats = {}
            st.session_state.circulation_path = []
            st.session_state.mentor_chat = []
            st.rerun()

    # --- NEW: RAPID CIRCULATION ROUTE BUILDER ---
    st.markdown("---")
    if assigned_students:
        # Clean up the path list just in case someone was deleted
        safe_path = [name for name in st.session_state.circulation_path if name in assigned_students]
        
        st.session_state.circulation_path = st.multiselect(
            "👣 Build Circulation Route (Select students in the order you will visit them):",
            options=assigned_students,
            default=safe_path,
            help="Click here to rapidly build your path without the page reloading on every click."
        )
    else:
        st.caption("*Seat some students to begin building a circulation route.*")

    # Front of Class Banner
    st.markdown("""
    <div style='text-align: center; background-color: #2C3E50; color: white; padding: 8px; border-radius: 8px; margin-bottom: 20px; font-weight: bold; letter-spacing: 3px; box-shadow: 0px 4px 6px rgba(0,0,0,0.1);'>
        👨‍🏫 FRONT OF CLASSROOM (WHITEBOARD) 👩‍🏫
    </div>
    """, unsafe_allow_html=True)
    
    # --- THE VISUAL GRID ---
    if layout_choice == "Rows (4x8)":
        for r in range(4):
            row_cols = st.columns(8, gap="small")
            for c in range(8):
                seat_idx = (r * 8) + c
                seat_key = f"seat_{seat_idx}"
                current_val = st.session_state.seats.get(seat_key, "Empty")
                with row_cols[c]:
                    render_seat_ui(seat_key, current_val, next_student, cohort, df)
                    
    else:
        for grp_row in range(2):
            table_cols = st.columns(4, gap="medium")
            for grp_col in range(4):
                table_idx = (grp_row * 4) + grp_col
                with table_cols[grp_col]:
                    with st.container(border=True):
                        st.markdown(f"<div style='text-align: center; font-weight: bold; font-size: 16px; margin-bottom: 15px; color: #2C3E50; border-bottom: 2px solid #3498db; padding-bottom: 5px;'>Table {table_idx + 1}</div>", unsafe_allow_html=True)
                        seat_start = table_idx * 4
                        t1, t2 = st.columns(2, gap="small")
                        with t1: render_seat_ui(f"seat_{seat_start}", st.session_state.seats.get(f"seat_{seat_start}", "Empty"), next_student, cohort, df)
                        with t2: render_seat_ui(f"seat_{seat_start+1}", st.session_state.seats.get(f"seat_{seat_start+1}", "Empty"), next_student, cohort, df)
                        b1, b2 = st.columns(2, gap="small")
                        with b1: render_seat_ui(f"seat_{seat_start+2}", st.session_state.seats.get(f"seat_{seat_start+2}", "Empty"), next_student, cohort, df)
                        with b2: render_seat_ui(f"seat_{seat_start+3}", st.session_state.seats.get(f"seat_{seat_start+3}", "Empty"), next_student, cohort, df)


    # --- AI MENTOR EVALUATION SECTION ---
    st.markdown("---")
    st.subheader("🤖 ITT Mentor: Plan Evaluation")
    
    layout_data = []
    if layout_choice == "Rows (4x8)":
        for r in range(4):
            row_students = []
            for c in range(8):
                seat_name = st.session_state.seats.get(f"seat_{(r * 8) + c}", "Empty")
                if seat_name != "Empty":
                    dots = get_student_dots(seat_name, df)
                    row_students.append(f"{seat_name} [{dots}]")
            if row_students:
                layout_data.append(f"Row {r+1} (Closest to front is Row 1): " + ", ".join(row_students))
    else:
        for t in range(8):
            table_students = []
            for s in range(4):
                seat_name = st.session_state.seats.get(f"seat_{(t * 4) + s}", "Empty")
                if seat_name != "Empty":
                    dots = get_student_dots(seat_name, df)
                    table_students.append(f"{seat_name} [{dots}]")
            if table_students:
                layout_data.append(f"Table {t+1}: " + ", ".join(table_students))

    layout_text = "\n".join(layout_data) if layout_data else "The classroom is empty."
    path_text = " -> ".join(st.session_state.circulation_path) if st.session_state.circulation_path else "None set."

    if st.button("Evaluate My Plan", type="primary"):
        if not api_key:
            st.error("API Key missing.")
            return

        with st.spinner("Your mentor is reviewing your seating plan and route..."):
            prompt = (
                "**[FICTIONAL SCENARIO FOR TEACHER TRAINING - ALL DATA IS MOCK/SYNTHETIC]**\n"
                "You are an expert ITT (Initial Teacher Training) Mentor evaluating a trainee's seating plan.\n\n"
                f"**Current Layout:**\n{layout_text}\n"
                f"**Circulation Route:**\n{path_text}\n\n"
                "Data Key: 🔴=SEN/SEND, 🟢=EAL, 🔵=Pupil Premium.\n\n"
                "Task:\n"
                "1. Briefly highlight one strength of their arrangement.\n"
                "2. Ask 1 or 2 constructive, probing questions to make them justify their choices. "
                "(e.g., 'I see you put three 🔴 students together at the back, how will you support them?', "
                "or 'Your circulation route completely misses Row 3, how will you check their understanding?').\n"
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
