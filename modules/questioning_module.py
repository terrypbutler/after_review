import streamlit as st
import random

def render_questioning_simulator(student_roster):
    """
    Renders the questioning simulator UI.
    Expects 'student_roster': a list of dictionaries containing student profiles.
    """
    st.header("Virtual Classroom: Questioning Strategies")
    st.markdown("Practice pedagogical decision-making with your Year 10 cohort.")

    # 1. INITIALIZE SESSION STATE
    # We must store inputs in session state so they survive button clicks
    if "teacher_text" not in st.session_state:
        st.session_state.teacher_text = ""
    if "question_locked" not in st.session_state:
        st.session_state.question_locked = False

    # 2. THE INPUT ZONE
    st.subheader("1. Set the Stimulus")
    
    # We use a form so the app doesn't refresh on every keystroke
    with st.form("question_setup_form"):
        col1, col2 = st.columns([2, 1])
        with col1:
            q_text = st.text_area("Teacher's Question/Prompt:", value=st.session_state.teacher_text)
        with col2:
            q_image = st.file_uploader("Upload Image (Optional)", type=["png", "jpg", "jpeg"])
        
        submitted = st.form_submit_button("Lock in Question")
        
        if submitted:
            if q_text == "" and q_image is None:
                st.warning("Please provide either text or an image.")
            else:
                st.session_state.teacher_text = q_text
                st.session_state.question_locked = True
                st.success("Question set. Select a strategy below.")

    st.divider()

    # 3. THE ACTION ZONE (Revealed only when a question is set)
    if st.session_state.question_locked:
        st.subheader("2. Select Questioning Strategy")
        
        tab_exit, tab_boards, tab_hands, tab_cold = st.tabs([
            "🚪 Exit Ticket", "📝 Mini-Whiteboards", "✋ Hands Up", "🎯 Cold Call"
        ])
        
        # --- MODE 1: EXIT TICKET ---
        with tab_exit:
            st.markdown("Collect detailed, independent written responses from the entire cohort.")
            if st.button("Collect Exit Tickets"):
                with st.spinner("Students are writing their answers..."):
                    for student in student_roster:
                        # AI API Call goes here
                        st.text_area(
                            f"{student['name']} ({student['ability']})", 
                            f"*(AI paragraph response for {student['name']} goes here)*", 
                            disabled=True
                        )

        # --- MODE 2: MINI-WHITEBOARDS ---
        with tab_boards:
            st.markdown("Get a simultaneous 1-to-5 word answer from everyone to check for understanding.")
            if st.button("Show Boards, 3-2-1!"):
                with st.spinner("Students are scribbling..."):
                    # Create a grid for the whiteboards (3 columns)
                    cols = st.columns(3)
                    for i, student in enumerate(student_roster):
                        with cols[i % 3]:
                            # AI API Call goes here
                            st.info(f"**{student['name']}**\n\n*(Short AI answer)*")

        # --- MODE 3: HANDS UP ---
        with tab_hands:
            st.markdown("See who volunteers to answer based on confidence and ability.")
            if st.button("Scan the Room"):
                with st.spinner("Wait time..."):
                    # AI Call: "Which of these students would raise their hand?"
                    # For now, we simulate this randomly
                    volunteers = [s for s in student_roster if random.choice([True, False])]
                    
                    if not volunteers:
                        st.warning("No one raised their hand. (Crickets...)")
                    else:
                        st.success(f"{len(volunteers)} students raised their hands:")
                        for v in volunteers:
                            if st.button(v['name'], key=f"hand_{v['name']}"):
                                # AI Call: "Give the verbal response for this specific student"
                                st.write(f"**{v['name']}:** *(AI verbal response here)*")

        # --- MODE 4: COLD CALL ---
        with tab_cold:
            st.markdown("Select a specific student to target, regardless of confidence.")
            student_names = [s['name'] for s in student_roster]
            target = st.selectbox("Select target student", student_names)
            
            if st.button(f"Call on {target}"):
                with st.spinner(f"Waiting for {target} to react..."):
                    # AI API Call goes here
                    st.success(f"**{target}:** *(AI verbal response, including hesitation if struggling)*")


# --- STANDALONE TESTING BLOCK ---
# This allows you to run `streamlit run questioning_module.py` directly
if __name__ == "__main__":
    st.set_page_config(page_title="Questioning Simulator", layout="wide")
    
    # Dummy Year 10 data to make the UI work before you connect your real database
    dummy_year_10_cohort = [
        {"name": "Alice", "ability": "High Performing", "notes": "Confident, sometimes rushes."},
        {"name": "Ben", "ability": "Average", "notes": "Quiet, needs encouragement."},
        {"name": "Charlie", "ability": "Struggling", "notes": "Math anxiety, gives up easily."},
        {"name": "Diana", "ability": "High Performing", "notes": "Very precise."},
        {"name": "Ethan", "ability": "Struggling", "notes": "Often misunderstands instructions."}
    ]
    
    render_questioning_simulator(dummy_year_10_cohort)
