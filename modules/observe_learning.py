import streamlit as st
import json
import random
import re
from PIL import Image
from config import REACTION_MODEL
from modules.app_secrets import get_secret
from modules import gemini_client as genai
from modules.photo_utils import display_student_photo

try:
    from modules.academic_responses import get_elevenlabs_audio
except ImportError:
    st.error("⚠️ Could not find get_elevenlabs_audio.")

def get_flexible_text(row, possible_names):
    row_keys = {str(k).strip().lower(): k for k in row.keys()}
    for name in possible_names:
        clean_name = name.lower().strip()
        if clean_name in row_keys:
            val = str(row[row_keys[clean_name]]).strip()
            if val and val.upper() not in ["NAN", "N/A", "NONE", "NULL", ""]:
                if val.endswith(".0"): val = val[:-2]
                return val
    return "None recorded"

def render_observation_room(df, cohort):
    col_header1, col_header2 = st.columns([3, 1])
    with col_header1:
        st.subheader("👁️ Circulate the Room: Full Class Observation")
    with col_header2:
        enable_voice = st.toggle("🔊 Voice Audio", value=True, key="obs_voice_toggle")

    api_key = get_secret("GEMINI_API_KEY")
    if not api_key:
        st.error("⚠️ Gemini API Key missing.")
        return
    genai.configure(api_key=api_key)

    # --- 1. INITIALIZE THE STATE MACHINE ---
    if "obs_task" not in st.session_state: st.session_state.obs_task = ""
    if "obs_image" not in st.session_state: st.session_state.obs_image = None
    if "live_observations" not in st.session_state: st.session_state.live_observations = {}
    if "obs_intervene_target" not in st.session_state: st.session_state.obs_intervene_target = None
    if "obs_active_students" not in st.session_state: st.session_state.obs_active_students = []
    
    if "obs_task_duration" not in st.session_state: st.session_state.obs_task_duration = 30
    if "obs_time_elapsed" not in st.session_state: st.session_state.obs_time_elapsed = 0
    if "obs_engagement_log" not in st.session_state: st.session_state.obs_engagement_log = None
    if "obs_global_event" not in st.session_state: st.session_state.obs_global_event = None
    
    if "student_states" not in st.session_state: st.session_state.student_states = {}

    # --- 2. THE 1-ON-1 INTERVENTION VIEW ---
    if st.session_state.obs_intervene_target:
        target_name = st.session_state.obs_intervene_target
        observation = st.session_state.live_observations.get(target_name, "")
        current_mot = st.session_state.student_states[target_name]["motivation"]
        
        st.markdown(f"### 🛑 Intervening with {target_name}")
        
        with st.container(border=True):
            st.markdown(f"**Current Task:** {st.session_state.obs_task}")
            if st.session_state.obs_global_event:
                st.warning(f"**Current Room Event:** {st.session_state.obs_global_event}")
            if st.session_state.obs_image is not None:
                with st.expander("🖼️ View Uploaded Task Resource"):
                    st.image(st.session_state.obs_image, width="stretch")
            st.info(f"**You observed:** {observation}")
        
        chat_key = f"obs_chat_{target_name}"
        if chat_key not in st.session_state: st.session_state[chat_key] = []

        col_a, col_b = st.columns([1, 3])
        with col_a:
            display_student_photo(target_name, cohort)
            st.metric("Current Motivation", f"{current_mot}%")
            if st.button("🔙 Step Away (Back to Room)", width="stretch"):
                st.session_state.obs_intervene_target = None
                st.rerun()

        with col_b:
            if "latest_audio_obs" in st.session_state:
                st.audio(st.session_state["latest_audio_obs"], format="audio/mp3", autoplay=True)
                del st.session_state["latest_audio_obs"]

            for msg in st.session_state[chat_key]:
                with st.chat_message(msg["role"]): st.write(msg["content"])

            teacher_input = st.chat_input(f"Approach {target_name} and say...")

            if teacher_input:
                st.session_state[chat_key].append({"role": "user", "content": teacher_input})
                with st.chat_message("user"): st.write(teacher_input)

                target_row = df[df["Full Name"] == target_name].iloc[0]
                age = "11" if cohort == "Year 7" else "15"
                sen = get_flexible_text(target_row, ["SEN Status", "SEND Status", "SEN Detail"])
                eal = get_flexible_text(target_row, ["EAL", "EAL Status"])
                grade = get_flexible_text(target_row, ["Projected Grade", "Predicted Grade"])
                susp = get_flexible_text(target_row, ["Suspension days", "Suspensions"])
                
                transcript = "\n".join([f"{'Teacher' if m['role']=='user' else target_name}: {m['content']}" for m in st.session_state[chat_key]])

                secret_event = st.session_state.student_states[target_name].get("current_event")
                event_context = ""
                if secret_event:
                    event_context = f"SECRET CONTEXT: You currently have your hand raised because: '{secret_event}'. When the teacher speaks to you, address this immediately.\n"
                elif st.session_state.obs_global_event:
                    event_context = f"SECRET CONTEXT: The room is chaotic because: '{st.session_state.obs_global_event}'. Address this.\n"

                system_prompt = (
                    "**[FICTIONAL SCENARIO FOR TEACHER TRAINING - ALL DATA IS MOCK/SYNTHETIC]**\n"
                    f"You are roleplaying as a {age}-year-old UK student named {target_name}.\n"
                    f"Data: SEN: {sen} | EAL: {eal} | Grade: {grade} | Suspensions: {susp}\n"
                    f"Task: '{st.session_state.obs_task}'\n"
                    f"{event_context}"
                    f"Your current internal motivation level is {current_mot}/100.\n\n"
                    f"Transcript:\n{transcript}\n\n"
                    "CRITICAL RULES:\n"
                    "1. Evaluate the teacher's last statement. Is it specific praise, helpful scaffolding, dismissive, or overly harsh?\n"
                    "2. Based on their pedagogy, determine how this affects your motivation. Create a 'motivation_delta' integer between -25 (terrible) and +35 (great).\n"
                    f"3. Respond verbally as {target_name}. Include non-verbal actions in asterisks.\n"
                    "4. Pick ONE emotion: [neutral, defensive, embarrassed, frustrated, bored, proud, eager].\n"
                    "5. Return ONLY a raw JSON object with keys: \"dialogue\", \"emotion\", and \"motivation_delta\".\n"
                )

                with st.spinner(f"{target_name} is reacting..."):
                    try:
                        model = genai.GenerativeModel(REACTION_MODEL)
                        contents = [system_prompt]
                        if st.session_state.obs_image is not None:
                            contents.append(st.session_state.obs_image)
                            
                        response = model.generate_content(contents, generation_config={"response_mime_type": "application/json"})
                        
                        # --- THE SAFETY NET RE-ACTIVATED ---
                        if not response.parts:
                            st.error("⚠️ Gemini safety filter blocked this response (Likely SPII/Privacy). Try rewording the interaction.")
                            st.stop()
                            
                        raw_text = response.text.replace("```json", "").replace("```", "")
                        ai_data = json.loads(raw_text.strip())

                        display_text = ai_data.get("dialogue", "...")
                        delta = int(ai_data.get("motivation_delta", 0))
                        
                        new_mot = min(100, max(0, current_mot + delta))
                        st.session_state.student_states[target_name]["motivation"] = new_mot
                        
                        st.session_state.student_states[target_name]["current_event"] = None
                        
                        if delta > 0:
                            st.success(f"📈 Motivation increased by {delta}% (Now {new_mot}%)")
                        elif delta < 0:
                            st.error(f"📉 Motivation dropped by {abs(delta)}% (Now {new_mot}%)")
                        else:
                            st.info(f"➖ Neutral interaction.")
                        
                    except Exception as e:
                        st.error(f"Gemini Error: {e}")
                        st.stop()

                st.session_state[chat_key].append({"role": "assistant", "content": display_text})
                with st.chat_message("assistant"): st.write(display_text)

                audio_text = re.sub(r'[*\[(].*?[*\])]', '', display_text).strip()

                if enable_voice and audio_text:
                    student_voice_id = target_row.get("Voice_Name", "JBFqnCBsd6RMkjVDRZzb")
                    audio_bytes = get_elevenlabs_audio(audio_text, student_voice_id)
                    if audio_bytes:
                        st.session_state["latest_audio_obs"] = audio_bytes
                        
                st.rerun()

    # --- 3. THE FULL ROOM VIEW ---
    else:
        st.markdown("### 1. Set the Independent Task")
        current_task = st.text_area("Describe the task:", placeholder="e.g., 'Copy the perspective drawing.'", value=st.session_state.obs_task)
        
        col_dur, col_up = st.columns(2)
        with col_dur:
            task_duration = st.number_input("Expected Task Duration (Minutes):", min_value=5, max_value=120, value=st.session_state.obs_task_duration, step=5)
        with col_up:
            uploaded_file = st.file_uploader("Upload reference resource (Optional)", type=['png', 'jpg', 'jpeg'])
            
        if uploaded_file is not None:
            st.image(uploaded_file, caption="Resource preview", width=300)
        
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("🚀 Initialize Full Class", type="primary", width="stretch"):
                if not current_task and uploaded_file is None:
                    st.warning("Please set a task description or upload a resource.")
                    st.stop()
                    
                st.session_state.obs_task = current_task
                st.session_state.obs_task_duration = task_duration
                st.session_state.obs_time_elapsed = 0
                st.session_state.obs_engagement_log = None 
                st.session_state.obs_global_event = None
                
                if uploaded_file is not None:
                    st.session_state.obs_image = Image.open(uploaded_file)
                else:
                    st.session_state.obs_image = None
                
                st.session_state.obs_active_students = df["Full Name"].tolist()
                
                for _, row in df.iterrows():
                    name = row["Full Name"]
                    grade = get_flexible_text(row, ["Projected Grade", "Predicted Grade"])
                    sen = get_flexible_text(row, ["SEN Status", "SEND Status"])
                    
                    st.session_state.student_states[name] = {
                        "motivation": random.randint(60, 90) if "7" in grade or "8" in grade or "9" in grade else random.randint(30, 60),
                        "progress": 0,
                        "decay_rate": random.randint(10, 20) if sen and sen.upper() != "NONE" else random.randint(5, 12),
                        "current_event": None
                    }
                
                st.session_state.live_observations = {name: "Waiting for task to begin." for name in st.session_state.obs_active_students}
                st.rerun()

        with col2:
            if st.session_state.obs_active_students:
                
                st.markdown("### ⚙️ Time Controls")
                advance_pct = st.slider("Advance Time (% of Total Duration):", min_value=5, max_value=100, value=10, step=5)
                
                step_minutes = round((advance_pct / 100.0) * st.session_state.obs_task_duration, 1)
                time_multiplier = step_minutes / 5.0 
                
                act_col1, act_col2 = st.columns(2)
                
                with act_col1:
                    if st.session_state.obs_time_elapsed == 0:
                        if st.button(f"👀 Watch Class Start (First {advance_pct}%)", type="secondary", width="stretch"):
                            st.session_state.obs_time_elapsed += step_minutes
                            
                            profiles = []
                            for name in st.session_state.obs_active_students:
                                mot = st.session_state.student_states[name]["motivation"]
                                profiles.append(f"- {name} | Motivation: {mot}%")
                            
                            start_prompt = (
                                "**[FICTIONAL SCENARIO FOR TEACHER TRAINING - ALL DATA IS MOCK/SYNTHETIC]**\n"
                                f"Task: '{current_task}'\n"
                                f"The teacher has just said 'Go!'. We are simulating the critical first {step_minutes} minutes.\n"
                                f"Current Class Profiles:\n{chr(10).join(profiles)}\n\n"
                                "CRITICAL RULES:\n"
                                "1. Determine exactly when each student engages with the task based on their motivation.\n"
                                "   - Motivation >70: Engages immediately (0:00 to 0:45).\n"
                                "   - Motivation 40-70: Delayed start (1:00 to 3:30).\n"
                                f"   - Motivation <40: Fails to start within {step_minutes} minutes (return 'Failed').\n"
                                "2. Provide a 1-sentence description of their start-up behavior.\n"
                                "3. Return ONLY a JSON dictionary where keys are names and values are dicts containing 'time' and 'desc'.\n"
                            )
                            
                            with st.spinner("Watching the room settle..."):
                                try:
                                    model = genai.GenerativeModel(REACTION_MODEL)
                                    contents = [start_prompt]
                                    if st.session_state.obs_image is not None: contents.append(st.session_state.obs_image)
                                        
                                    response = model.generate_content(contents, generation_config={"response_mime_type": "application/json"})
                                    
                                    if not response.parts:
                                        st.error("⚠️ Gemini safety filter blocked the room generation.")
                                        st.stop()
                                        
                                    raw_text = response.text.replace("```json", "").replace("```", "")
                                    log_data = json.loads(raw_text.strip())
                                    
                                    st.session_state.obs_engagement_log = log_data
                                    
                                    for name, data in log_data.items():
                                        st.session_state.live_observations[name] = data.get("desc", "")
                                        if data.get("time") != "Failed":
                                            prog_amount = int(random.randint(5, 15) * time_multiplier)
                                            st.session_state.student_states[name]["progress"] = min(100, st.session_state.student_states[name]["progress"] + prog_amount)
                                            
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Failed to track start: {e}")
                                    
                    else:
                        if st.button(f"⏱️ Advance Time ({advance_pct}%) & Scan Room", width="stretch"):
                            st.session_state.obs_time_elapsed += step_minutes
                            if st.session_state.obs_time_elapsed > st.session_state.obs_task_duration:
                                st.session_state.obs_time_elapsed = st.session_state.obs_task_duration
                            
                            st.session_state.obs_global_event = None
                            global_prompt_injection = ""
                            
                            dice_roll = random.randint(1, 100)
                            if dice_roll <= 2:
                                st.session_state.obs_global_event = "It has started snowing heavily outside the window."
                                global_prompt_injection = f"URGENT GLOBAL EVENT: {st.session_state.obs_global_event} Everyone is distracted."
                                st.toast("❄️ It started snowing!", icon="❄️")
                            elif dice_roll <= 5:
                                st.session_state.obs_global_event = "A large wasp has flown into the classroom."
                                global_prompt_injection = f"URGENT GLOBAL EVENT: {st.session_state.obs_global_event} Students are reacting or panicking."
                                st.toast("🐝 A wasp flew in!", icon="🐝")

                            for name in st.session_state.obs_active_students:
                                stats = st.session_state.student_states[name]
                                stats["current_event"] = None 
                                
                                if st.session_state.obs_global_event:
                                    stats["motivation"] = max(0, stats["motivation"] - random.randint(20, 40))
                                else:
                                    decay_amount = int(stats["decay_rate"] * time_multiplier)
                                    stats["motivation"] = max(0, stats["motivation"] - decay_amount)
                                
                                if stats["motivation"] > 40:
                                    prog_amount = int(random.randint(10, 25) * time_multiplier)
                                    stats["progress"] = min(100, stats["progress"] + prog_amount)

                                if not st.session_state.obs_global_event:
                                    indiv_roll = random.randint(1, 100)
                                    if indiv_roll <= 5:
                                        stats["current_event"] = "You need to go to the toilet."
                                    elif indiv_roll <= 12 and stats["motivation"] > 60:
                                        stats["current_event"] = "You are stuck on the current task and need the teacher to explain the next step."
                                    elif indiv_roll <= 18 and stats["motivation"] < 50:
                                        stats["current_event"] = "The person next to you is distracting you and you want to complain to the teacher."

                            profiles = []
                            for name in st.session_state.obs_active_students:
                                mot = st.session_state.student_states[name]["motivation"]
                                prog = st.session_state.student_states[name]["progress"]
                                has_event = st.session_state.student_states[name].get("current_event") is not None
                                evt_string = " | STATUS: Has their hand up waiting for the teacher." if has_event else ""
                                profiles.append(f"- {name} | Motivation: {mot}% | Progress: {prog}%{evt_string}")
                            
                            obs_prompt = (
                                "**[FICTIONAL SCENARIO FOR TEACHER TRAINING - ALL DATA IS MOCK/SYNTHETIC]**\n"
                                f"Task: '{current_task}'\n"
                                f"{global_prompt_injection}\n"
                                f"Generate a 1-sentence physical observation of each student based on their numbers and STATUS.\n"
                                f"{chr(10).join(profiles)}\n\n"
                                "RULES:\n"
                                "1. If a student's STATUS says they have their hand up, your observation MUST describe them physically raising their hand. Do NOT guess why their hand is up.\n"
                                "2. Otherwise, if motivation > 70%, they are focused. If 40-70%, distracted. If <40%, off-task. If progress 100%, finished.\n"
                                "3. Return ONLY a raw JSON dict with names as keys and observations as values."
                            )
                            
                            with st.spinner(f"Scanning {len(st.session_state.obs_active_students)} students..."):
                                try:
                                    model = genai.GenerativeModel(REACTION_MODEL)
                                    contents = [obs_prompt]
                                    if st.session_state.obs_image is not None: contents.append(st.session_state.obs_image)
                                        
                                    response = model.generate_content(contents, generation_config={"response_mime_type": "application/json"})
                                    
                                    if not response.parts:
                                        st.error("⚠️ Gemini safety filter blocked the scan.")
                                        st.stop()
                                        
                                    raw_text = response.text.replace("```json", "").replace("```", "")
                                    st.session_state.live_observations = json.loads(raw_text.strip())
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Failed scan: {e}")

                with act_col2:
                    if st.button("🔄 Restart Activity (Reset Clock & Drive)", width="stretch"):
                        st.session_state.obs_time_elapsed = 0
                        st.session_state.obs_engagement_log = None
                        st.session_state.obs_global_event = None
                        
                        for name in st.session_state.obs_active_students:
                            row = df[df["Full Name"] == name].iloc[0]
                            grade = get_flexible_text(row, ["Projected Grade", "Predicted Grade"])
                            sen = get_flexible_text(row, ["SEN Status", "SEND Status"])
                            
                            st.session_state.student_states[name] = {
                                "motivation": random.randint(60, 90) if "7" in grade or "8" in grade or "9" in grade else random.randint(30, 60),
                                "progress": 0,
                                "decay_rate": random.randint(10, 20) if sen and sen.upper() != "NONE" else random.randint(5, 12),
                                "current_event": None
                            }
                        
                        st.session_state.live_observations = {name: "Waiting for task to begin." for name in st.session_state.obs_active_students}
                        st.rerun()

        st.markdown("---")

        # SECTION B: Live Class Dashboard
        if st.session_state.obs_active_students:
            
            if st.session_state.obs_global_event:
                st.error(f"🚨 **Attention!** {st.session_state.obs_global_event}")

            progress_fraction = min(1.0, st.session_state.obs_time_elapsed / st.session_state.obs_task_duration)
            st.progress(progress_fraction)
            st.markdown(f"<div style='text-align: center; font-weight: bold; margin-bottom: 20px; color: #555;'>⏱️ Time Elapsed: {st.session_state.obs_time_elapsed:g} / {st.session_state.obs_task_duration:g} Minutes</div>", unsafe_allow_html=True)
            
            if st.session_state.obs_engagement_log is not None:
                with st.expander("📋 Latency to Engage (Start-up Tracker)", expanded=False):
                    col_fast, col_slow, col_fail = st.columns(3)
                    with col_fast:
                        st.markdown("🟢 **Immediate Start**")
                        for name, data in st.session_state.obs_engagement_log.items():
                            t = data.get("time", "Failed")
                            if t != "Failed" and int(t.split(":")[0]) < 1:
                                st.markdown(f"**{name}** ({t})")
                    with col_slow:
                        st.markdown("🟡 **Delayed Start**")
                        for name, data in st.session_state.obs_engagement_log.items():
                            t = data.get("time", "Failed")
                            if t != "Failed" and int(t.split(":")[0]) >= 1:
                                st.markdown(f"**{name}** ({t})")
                    with col_fail:
                        st.markdown("🔴 **Failed to Engage**")
                        for name, data in st.session_state.obs_engagement_log.items():
                            t = data.get("time", "Failed")
                            if t == "Failed":
                                st.markdown(f"**{name}**")
                st.markdown("---")
            
            total_mot = sum(st.session_state.student_states[name]["motivation"] for name in st.session_state.obs_active_students)
            total_prog = sum(st.session_state.student_states[name]["progress"] for name in st.session_state.obs_active_students)
            avg_mot = int(total_mot / len(st.session_state.obs_active_students))
            avg_prog = int(total_prog / len(st.session_state.obs_active_students))
            
            dash_col1, dash_col2, dash_col3 = st.columns(3)
            with dash_col1: st.metric("Class Average Motivation", f"{avg_mot}%")
            with dash_col2: st.metric("Class Average Progress", f"{avg_prog}%")
            with dash_col3: st.metric("Students Monitored", len(st.session_state.obs_active_students))
            
            st.markdown("### 📢 Broadcast to Class")
            st.caption("Address the entire room at once. Use this to reset focus, give a time warning, or clarify the task.")
            
            class_announcement = st.chat_input("Speak to the entire class...")
            if class_announcement:
                with st.spinner("The class is processing your announcement..."):
                    profiles_str = "\n".join([f"- {name} (Mot: {st.session_state.student_states[name]['motivation']}%)" for name in st.session_state.obs_active_students])
                    
                    broadcast_prompt = (
                        "**[FICTIONAL SCENARIO FOR TEACHER TRAINING - ALL DATA IS MOCK/SYNTHETIC]**\n"
                        f"The teacher just addressed the entire class aloud: '{class_announcement}'\n\n"
                        f"Current Class Profiles:\n{profiles_str}\n\n"
                        "CRITICAL RULES:\n"
                        "1. Evaluate the pedagogical impact of this announcement. Does it inspire, panic, or refocus them?\n"
                        "2. Create a 'delta' (-20 to +30) showing how it affects EACH student's motivation based on their current state.\n"
                        "3. Write a 1-sentence 'reaction' for each student.\n"
                        "4. Return ONLY a JSON dictionary where the keys are student names, and the values are dictionaries containing 'delta' and 'reaction'.\n"
                    )
                    
                    try:
                        model = genai.GenerativeModel(REACTION_MODEL)
                        response = model.generate_content(broadcast_prompt, generation_config={"response_mime_type": "application/json"})
                        
                        if not response.parts:
                            st.error("⚠️ Gemini safety filter blocked the class reaction.")
                            st.stop()
                            
                        raw_text = response.text.replace("```json", "").replace("```", "")
                        reaction_data = json.loads(raw_text.strip())
                        
                        for name, data in reaction_data.items():
                            if name in st.session_state.student_states:
                                current_m = st.session_state.student_states[name]["motivation"]
                                delta = data.get("delta", 0)
                                st.session_state.student_states[name]["motivation"] = min(100, max(0, current_m + delta))
                                st.session_state.live_observations[name] = data.get("reaction", "Listened.")
                        
                        st.session_state.obs_global_event = None
                        st.success(f"📣 You said: '{class_announcement}' — The room has reacted.")
                        
                    except Exception as e:
                        st.error(f"Failed to process class announcement: {e}")

            st.markdown("---")
            
            # SECTION C: The Student Grid
            num_cols = 4
            for i in range(0, len(st.session_state.obs_active_students), num_cols):
                cols = st.columns(num_cols)
                for idx, student_name in enumerate(st.session_state.obs_active_students[i : i + num_cols]):
                    with cols[idx]:
                        with st.container(border=True):
                            display_student_photo(student_name, cohort)
                            st.markdown(f"**{student_name}**")
                            
                            stats = st.session_state.student_states[student_name]
                            
                            mot_color = "🟢" if stats["motivation"] > 65 else "🟡" if stats["motivation"] > 35 else "🔴"
                            st.caption(f"{mot_color} **Drive:** {stats['motivation']}% | 📋 **Done:** {stats['progress']}%")
                            
                            if stats.get("current_event"):
                                st.warning(f"🙋 **Hand Raised**")
                            
                            obs_text = st.session_state.live_observations.get(student_name, "Waiting for scan...")
                            st.info(f"*{obs_text}*")
                            
                            if st.button("🗣️ Intervene", key=f"int_{student_name}", width="stretch"):
                                st.session_state.obs_intervene_target = student_name
                                st.rerun()
