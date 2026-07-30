import streamlit as st
import json
import re
from config import REACTION_MODEL
from modules.app_shell import (
    get_teacher_address_instruction,
    get_teacher_address_options,
    get_teacher_display_name,
)
from modules.app_secrets import get_secret
from modules import gemini_client as genai
from modules.data_utils import get_ai_response_profile
from modules.photo_utils import display_student_photo

try:
    from modules.academic_responses import get_elevenlabs_audio
except ImportError:
    st.error("⚠️ Could not find get_elevenlabs_audio in modules.academic_responses")

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

def render_simulator(df, cohort):
    teacher_name = get_teacher_display_name()
    teacher_addresses = get_teacher_address_options(teacher_name)
    col_header1, col_header2 = st.columns([3, 1])
    with col_header1:
        st.subheader("🤖 Virtual Student Simulator")
    with col_header2:
        enable_voice = st.toggle("🔊 Voice Audio", value=True, key="sim_voice_toggle")

    api_key = get_secret("GEMINI_API_KEY")
    if not api_key:
        st.error("⚠️ Gemini API Key missing.")
        return

    genai.configure(api_key=api_key)

    student_list = df["Full Name"].tolist()
    selected_student = st.selectbox("Select Student to Roleplay:", student_list)

    if not selected_student:
        return

    row = df[df["Full Name"] == selected_student].iloc[0]

    age = "11" if cohort == "Year 7" else "15"
    sen = get_flexible_text(row, ["SEN Status", "SEND Status", "SEN Detail"])
    home_life = get_flexible_text(row, ["Home Life & Interests", "Home Life", "Interests"])
    predicted = get_flexible_text(row, ["Projected Grade", "Predicted Grade"])
    eal = get_flexible_text(row, ["EAL", "EAL Status"])
    response_profile = get_ai_response_profile(row, cohort)
    teacher_key = re.sub(
        r"[^a-z0-9]+",
        "_",
        "|".join(teacher_addresses).casefold(),
    ).strip("_")
    chat_key = f"chat_{selected_student}_{teacher_key or 'teacher'}"

    st.markdown("---")
    address_labels = " or ".join(
        f"**{address}**"
        for address in teacher_addresses
    )
    st.caption(
        f"Teacher speaker label: **{teacher_name}** · Pupils may address you as "
        f"{address_labels}. Change this in the sidebar."
    )

    col1, col2 = st.columns([1, 2])

    with col1:
        with st.container(border=True):
            display_student_photo(selected_student, cohort)
            st.markdown("**Target Profile:**")
            st.caption(f"**SEN:** {sen}")
            st.caption(f"**EAL:** {eal}")
            st.caption(f"**Grade:** {predicted}")
            st.caption(f"**Home:** {home_life[:60]}...")

        scenario = st.radio("Scenario:", ["End of Lesson", "Corridor Behavior", "Struggling with Task"])
        if st.button("🔄 Reset Chat", width="stretch"):
            st.session_state[chat_key] = []
            st.rerun()

    with col2:
        if "latest_audio_sim" in st.session_state:
            st.audio(st.session_state["latest_audio_sim"], format="audio/mp3", autoplay=True)
            del st.session_state["latest_audio_sim"]

        if chat_key not in st.session_state:
            st.session_state[chat_key] = []

        for msg in st.session_state[chat_key]:
            with st.chat_message(msg["role"]):
                speaker = (
                    teacher_name
                    if msg["role"] == "user"
                    else selected_student
                )
                st.markdown(f"**{speaker}**")
                st.write(msg["content"])

        teacher_input = st.chat_input(f"Say something to {selected_student}...")

        if teacher_input:
            st.session_state[chat_key].append({"role": "user", "content": teacher_input})
            with st.chat_message("user"):
                st.markdown(f"**{teacher_name}**")
                st.write(teacher_input)

            recent_messages = st.session_state[chat_key][-8:]
            transcript = "\n".join(
                f"{teacher_name if m['role']=='user' else selected_student}: {m['content']}"
                for m in recent_messages
            )
            address_instruction = get_teacher_address_instruction(teacher_name)
            example_address = teacher_addresses[-1]

            system_prompt = (
                f"You are roleplaying as a {age}-year-old UK student named {selected_student}.\n"
                f"Compact pupil response profile: {response_profile}\n"
                f"Scenario: {scenario}.\n\n"
                f"{address_instruction}\n\n"
                f"Transcript:\n{transcript}\n\n"
                "CRITICAL RULES:\n"
                f"1. Respond as {selected_student}. Keep it short (1-3 sentences).\n"
                "2. MUST include non-verbal body language wrapped in asterisks (e.g., *rolls eyes*, *sighs*).\n"
                "3. Determine the student's current emotion based on the scenario and teacher's prompt. Pick ONE: [neutral, angry, defensive, sad, bored, hesitant, excited, eager].\n"
                "4. You MUST return your response as a raw JSON object with two keys: \"dialogue\" and \"emotion\".\n\n"
                "Example Format:\n"
                f"{{\"dialogue\": \"*crosses arms* I don't know why you're picking on "
                f"me, {example_address}.\", \"emotion\": \"defensive\"}}"
            )

            # --- 1. FAST TEXT GENERATION ---
            with st.spinner(f"{selected_student} is typing..."):
                try:
                    model = genai.GenerativeModel(REACTION_MODEL)
                    response = model.generate_content(system_prompt, generation_config={"response_mime_type": "application/json"})

                    if not response.parts:
                        st.error("⚠️ Gemini refused to answer. The scenario likely triggered a safety filter.")
                        st.stop()

                    raw_text = response.text.replace("```json", "").replace("```", "")
                    ai_data = json.loads(raw_text.strip())

                    display_text = ai_data.get("dialogue", "...")
                    current_emotion = ai_data.get("emotion", "neutral")
                    
                except Exception as e:
                    st.error(f"Gemini API Error: {e}")
                    st.stop()

            # SPEED HACK: Instantly show the text on screen BEFORE generating audio
            st.session_state[chat_key].append({"role": "assistant", "content": display_text})
            with st.chat_message("assistant"):
                st.markdown(f"**{selected_student}**")
                st.write(display_text)
                
            st.toast(f"Student Mood: {current_emotion.upper()} 🎭")

            # --- THE SCRUBBER: Remove actions for the audio engine ---
            # This deletes anything wrapped in *, [, or ( so ElevenLabs doesn't read it
            audio_text = re.sub(r'[*\[(].*?[*\])]', '', display_text).strip()

            # --- 2. BACKGROUND AUDIO GENERATION ---
            # Only run ElevenLabs if the voice is toggled ON and there is actually text left to speak
            if enable_voice and audio_text:
                with st.spinner(f"Generating audio..."):
                    try:
                        student_voice_id = row.get("Voice_Name", "JBFqnCBsd6RMkjVDRZzb")
                        
                        # We pass the pure, scrubbed text directly to ElevenLabs
                        audio_bytes = get_elevenlabs_audio(
                            audio_text,
                            student_voice_id,
                            cohort,
                        )

                        if audio_bytes is None:
                            st.warning("ElevenLabs audio failed.")
                        else:
                            st.session_state["latest_audio_sim"] = audio_bytes
                            st.rerun() 
                            
                    except Exception as e:
                        st.error(f"Audio Error: {e}")
            else:
                st.stop()
