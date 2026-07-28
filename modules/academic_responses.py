import streamlit as st
from elevenlabs import VoiceSettings
from elevenlabs.client import ElevenLabs
import json
import time
import random
import re
from PIL import Image
from config import REACTION_MODEL
from modules.app_secrets import get_secret
from modules import gemini_client as genai
from modules.data_utils import get_ai_response_profile
from modules.photo_utils import display_student_photo

_AFL_DISCUSSION_KEY = "afl_discussion"
_AFL_STARTED_INTERACTIONS_KEY = "afl_started_interactions"
_AFL_EXIT_ANSWERS_KEY = "afl_exit_answers"


def _ensure_afl_state():
    if _AFL_DISCUSSION_KEY not in st.session_state:
        st.session_state[_AFL_DISCUSSION_KEY] = []
    if _AFL_STARTED_INTERACTIONS_KEY not in st.session_state:
        st.session_state[_AFL_STARTED_INTERACTIONS_KEY] = []
    if _AFL_EXIT_ANSWERS_KEY not in st.session_state:
        st.session_state[_AFL_EXIT_ANSWERS_KEY] = None


def _append_afl_comment(role, speaker, content, source="spoken", marker=None):
    """Add one contribution to the shared AfL discussion."""
    _ensure_afl_state()
    clean_content = str(content).strip()
    if not clean_content:
        return False

    if marker and any(
        entry.get("marker") == marker
        for entry in st.session_state[_AFL_DISCUSSION_KEY]
    ):
        return False

    st.session_state[_AFL_DISCUSSION_KEY].append(
        {
            "role": role,
            "speaker": str(speaker).strip() or ("Teacher" if role == "teacher" else "Student"),
            "content": clean_content,
            "source": source,
            "marker": marker,
        }
    )
    return True


def _record_opening_question(teacher_name, teacher_question):
    clean_question = str(teacher_question).strip()
    return _append_afl_comment(
        "teacher",
        teacher_name,
        clean_question,
        marker=f"opening-question::{clean_question}",
    )


def build_afl_transcript(comments):
    """Return a speaker-labelled transcript for Gemini's shared class memory."""
    transcript_lines = []
    for comment in comments:
        role = comment.get("role", "student")
        speaker = comment.get("speaker") or ("Teacher" if role == "teacher" else "Student")
        source = comment.get("source", "spoken")
        source_label = " [written answer]" if source == "whiteboard" else ""
        transcript_lines.append(f"{speaker}{source_label}: {comment.get('content', '')}")
    return "\n".join(transcript_lines)


def _afl_transcript():
    _ensure_afl_state()
    return build_afl_transcript(st.session_state[_AFL_DISCUSSION_KEY])


def _render_afl_discussion():
    _ensure_afl_state()
    comments = st.session_state[_AFL_DISCUSSION_KEY]

    st.markdown("### 💬 Remembered class discussion")
    st.caption(
        "Every contribution is remembered across students and questioning strategies. "
        "Invite another student to agree, challenge or improve an earlier answer."
    )

    if not comments:
        st.info("The discussion will appear here after the first student responds.")
        return

    with st.container(border=True):
        for comment in comments:
            message_type = "user" if comment.get("role") == "teacher" else "assistant"
            speaker = comment.get("speaker", "Student")
            source_label = " · whiteboard" if comment.get("source") == "whiteboard" else ""
            message_text = str(comment.get("content", "")).replace("\n", "\n\n")
            with st.chat_message(message_type):
                st.markdown(f"**{speaker}{source_label}:** {message_text}")


def _interaction_token(strategy, target_name, teacher_question):
    return f"{strategy}::{target_name}::{str(teacher_question).strip()}"


def _interaction_started(token):
    _ensure_afl_state()
    return token in st.session_state[_AFL_STARTED_INTERACTIONS_KEY]


def _mark_interaction_started(token):
    _ensure_afl_state()
    if token not in st.session_state[_AFL_STARTED_INTERACTIONS_KEY]:
        st.session_state[_AFL_STARTED_INTERACTIONS_KEY].append(token)


def _reset_academic_afl_state():
    """Start a completely new AfL activity while preserving voice preference."""
    reset_keys = {
        _AFL_DISCUSSION_KEY,
        _AFL_STARTED_INTERACTIONS_KEY,
        _AFL_EXIT_ANSWERS_KEY,
        "wb_answers",
        "wb_probe_selected",
        "hu_volunteers",
        "hu_selected",
        "latest_audio",
        "afl_teacher_question",
        "afl_resource_upload",
        "afl_strategy",
        "afl_cold_call_student",
    }
    for key in list(st.session_state.keys()):
        if key in reset_keys or str(key).startswith("probe_chat_"):
            del st.session_state[key]


def generate_discussion_reply(target_name, target_row, cohort, subject, teacher_name):
    """Generate a student's response using the whole remembered class discussion."""
    response_profile = get_ai_response_profile(target_row, cohort, subject)
    transcript = _afl_transcript()

    chat_prompt = f"""
    You are roleplaying as {target_name}, a {cohort} student.
    The subject is {subject}. The teacher's name/title is {teacher_name}.
    Use this compact pupil response profile:
    {response_profile}

    This is the whole-class discussion so far. It includes comments from the teacher
    and potentially several different students:
    {transcript}

    CRITICAL RULES:
    1. Respond as {target_name} to the teacher's latest comment or instruction. Keep it brief (1-2 sentences).
    2. Remember every earlier contribution. If asked about another student's answer,
       explicitly agree, disagree, correct, extend or improve it in a realistic way.
    3. Do not claim that another student's comment was your own.
    4. Match the student's likely attainment and needs; do not automatically make every answer correct.
    5. Determine the student's current emotion. Pick ONE:
       [neutral, angry, defensive, sad, bored, hesitant, excited, eager].
    6. Return a raw JSON object with exactly two keys: "dialogue" and "emotion".

    Example:
    {{"dialogue": "I agree with Alex about the first step, but I think we divide by 2 next, {teacher_name}.", "emotion": "hesitant"}}
    """

    model = genai.GenerativeModel(REACTION_MODEL)
    response = model.generate_content(
        chat_prompt,
        generation_config={"response_mime_type": "application/json"},
    )
    ai_data = json.loads(response.text)
    return ai_data.get("dialogue", "..."), ai_data.get("emotion", "neutral")


def _voice_settings_for_cohort(cohort):
    """Keep a pupil's voice identity while giving Year 10 a subtler cadence."""
    is_year_10 = str(cohort).strip().casefold() == "year 10"
    return {
        "stability": 0.56 if is_year_10 else 0.50,
        "similarity_boost": 0.80,
        "style": 0.0,
        "use_speaker_boost": True,
        "speed": 0.96 if is_year_10 else 1.0,
    }


def get_elevenlabs_audio(
    text,
    voice_id="JBFqnCBsd6RMkjVDRZzb",
    cohort="Year 7",
):
    api_key = get_secret("ELEVENLABS_API_KEY")
    if not api_key:
        st.error("⚠️ ELEVENLABS_API_KEY missing.")
        return None
        
    try:
        client = ElevenLabs(api_key=api_key)
        audio_generator = client.text_to_speech.convert(
            text=text,
            voice_id=voice_id,
            model_id="eleven_flash_v2_5",
            output_format="mp3_44100_96",
            voice_settings=VoiceSettings(**_voice_settings_for_cohort(cohort)),
        )
        return b"".join(audio_generator)
    except Exception as e:
        st.error(f"ElevenLabs Error: {e}")
        return None

def get_flexible_text(row, possible_names, default="None recorded"):
    row_keys = {str(k).strip().lower(): k for k in row.keys()}
    for name in possible_names:
        clean_name = name.lower().strip()
        if clean_name in row_keys:
            val = str(row[row_keys[clean_name]]).strip()
            if val and val.upper() not in ["NAN", "N/A", "NONE", "NULL", ""]:
                if val.endswith(".0"): val = val[:-2]
                return val
    return default

def fetch_ai_answers(
    question,
    student_subset,
    instructions,
    uploaded_file,
    cohort,
    subject,
    teacher_name,
    is_written=False,
    discussion_history="",
):
    age_context = "11 to 12 years old" if cohort == "Year 7" else "14 to 15 years old"
    
    profiles = []
    for _, row in student_subset.iterrows():
        name = row.get("Full Name")
        response_profile = get_ai_response_profile(row, cohort, subject)
        profiles.append(f"- {name}: {response_profile}")
        
    profiles_text = "\n".join(profiles)
    
    if is_written:
        address_rule = "4. Written Work: DO NOT use the teacher's name or titles like 'Sir' or 'Miss' in the response. It must read entirely like an exercise book or whiteboard."
    else:
        address_rule = f"4. Teacher Address: The students should occasionally use the teacher's name/title ('{teacher_name}') naturally in their verbal responses (e.g., 'I think it's 4, {teacher_name}')."
    
    prompt = f"""
    A trainee teacher (addressed as '{teacher_name}') is conducting a {subject} lesson for a class of {cohort} students (approximate age: {age_context}).
    The teacher has asked the class: "{question}"
    
    Here are the compact, privacy-minimised response profiles for the students answering:
    {profiles_text}
    
    {instructions}

    Remembered whole-class discussion:
    {discussion_history or "No students have contributed yet."}
    
    CRITICAL PEDAGOGICAL CONSTRAINTS:
    1. Ability Match: Scale vocabulary, accuracy, length, and depth to the compact profile.
    2. Deep Misconceptions: Inject realistic, {subject}-specific misconceptions or partial misunderstandings for lower grades.
    3. Participation Match: Use the pupil's confidence, participation, processing and discussion style; do not invent private background information.
    {address_rule}
    5. Math Formatting: Make maths look like real maths. DO NOT use raw carets (like r^2). You MUST use Unicode superscripts (e.g., r², x³, y₁) and symbols (π, √, ÷, ×, ±). For complex equations, use LaTeX wrapped in single `$` (e.g., `$x = \\frac{{1}}{{2}}$`).
    6. Layout: If the answer involves multiple steps of calculation, you MUST put each step on a new line using a newline character (\\n).
    
    CRITICAL TECHNICAL RULES:
    - Return ONLY a valid JSON dictionary where keys are exact student names and values are their answers.
    - If you use LaTeX, you MUST double-escape the backslashes (e.g., `\\\\frac`, `\\\\sqrt`) so the JSON parser does not crash.
    """
    
    for attempt in range(3):
        try:
            model = genai.GenerativeModel(REACTION_MODEL)
            contents = [prompt]
            if uploaded_file is not None: contents.append(Image.open(uploaded_file))
                
            response = model.generate_content(contents, generation_config={"response_mime_type": "application/json"})
            
            raw_text = response.text
            raw_text = raw_text.replace("`" * 3 + "json", "")
            raw_text = raw_text.replace("`" * 3, "")
            return json.loads(raw_text.strip())
            
        except Exception as e:
            if "429" in str(e) and attempt < 2:
                st.toast(f"🚦 AI Speed Limit hit. Auto-retrying in 20 seconds...")
                time.sleep(20)
            elif attempt == 2:
                st.error("🚦 AI exhausted. Please wait 60 seconds.")
                return {}
    return {}

def create_printable_worksheet(question, answers, df, subject, cohort):
    html = [
        "<!DOCTYPE html><html><head><meta charset='UTF-8'><title>Marking Practice</title>",
        "<script src='https://polyfill.io/v3/polyfill.min.js?features=es6'></script>",
        "<script id='MathJax-script' async src='https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js'></script>",
        "<style>",
        "body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 40px; color: #222; line-height: 1.5; }",
        "@media print { body { margin: 0; -webkit-print-color-adjust: exact; print-color-adjust: exact; } .student-box { page-break-inside: avoid; } }",
        ".header { text-align: center; border-bottom: 2px solid #2C3E50; padding-bottom: 10px; margin-bottom: 20px; }",
        ".reflection-box { background: #e8f4f8; border: 2px solid #3498DB; padding: 20px; margin-bottom: 30px; border-radius: 8px; }",
        ".reflection-box h3 { margin-top: 0; color: #2C3E50; font-size: 18px; }",
        ".reflection-box ul { margin: 0; padding-left: 20px; font-weight: bold; color: #333; font-size: 15px; }",
        ".reflection-box li { margin-bottom: 6px; }",
        ".question-box { background: #f8f9fa; padding: 15px; border-left: 5px solid #E67E22; margin-bottom: 30px; font-size: 16px; }",
        ".student-box { border: 2px solid #ddd; padding: 20px; margin-bottom: 25px; border-radius: 8px; }",
        ".student-name { font-size: 18px; font-weight: bold; color: #2C3E50; margin-bottom: 4px; }",
        ".student-profile { font-size: 12px; color: #666; margin-bottom: 12px; background: #eee; display: inline-block; padding: 3px 8px; border-radius: 4px; }",
        ".student-answer { font-size: 15px; margin-bottom: 30px; line-height: 1.6; font-family: 'Comic Sans MS', 'Chalkboard SE', sans-serif; color: #000080; }",
        "del { color: #d9534f; text-decoration: line-through; }", 
        ".marking-area { border-top: 2px dashed #ccc; padding-top: 15px; min-height: 120px; }",
        ".marking-title { font-weight: bold; font-size: 14px; color: #E67E22; text-transform: uppercase; letter-spacing: 1px; }",
        "</style></head><body>",
        f"<div class='header'><h2>ITT Marking Practice: {cohort} {subject}</h2></div>",
        "<div class='reflection-box'>",
        "<h3>Trainee Reflection Prompts:</h3>",
        "<ul>",
        "<li>Who understands the problem but still loses marks?</li>",
        "<li>Who doesn’t finish — and why?</li>",
        "<li>Which responses would collapse under exam conditions?</li>",
        "<li>If this was your class, what would you do now?</li>",
        "<li>Who needs scaffolding not stretch?</li>",
        "<li>Who needs slowing down not challenge?</li>",
        "<li>Who needs feedback on presentation, not maths?</li>",
        "</ul>",
        "</div>",
        f"<div class='question-box'><strong>Teacher's Prompt / Exit Ticket Question:</strong><br><br>{question}</div>"
    ]

    for _, row in df.iterrows():
        name = row.get("Full Name", "Unknown")
        grade = get_flexible_text(row, ["Projected Grade", "Predicted Grade"])
        sen = get_flexible_text(row, ["SEN Status", "SEND Status"])
        
        raw_ans = answers.get(name, "No response submitted.")
        
        html_ans = re.sub(r'~~(.*?)~~', r'<del>\1</del>', str(raw_ans))
        html_ans = html_ans.replace("\n", "<br>")

        profile_text = f"Target: {grade}"
        if sen and sen.upper() not in ["N/A", "NONE", "NO", "N", ""]:
            profile_text += f" | SEN: {sen}"

        html.append(f"<div class='student-box'>")
        html.append(f"<div class='student-name'>{name}</div>")
        html.append(f"<div class='student-profile'>Context for Trainee: {profile_text}</div>")
        html.append(f"<div class='student-answer'>{html_ans}</div>")
        html.append(f"<div class='marking-area'><span class='marking-title'>Trainee Feedback / Next Steps:</span></div>")
        html.append(f"</div>")

    html.append("</body></html>")
    return "\n".join(html)

def render_academic_responses(df, cohort, subject="General"):
    _ensure_afl_state()

    # --- HEADER & MASTER TOGGLE ---
    col_header1, col_header2, col_header3 = st.columns([3, 1, 1.35])
    with col_header1:
        st.subheader(f"🎓 AfL Simulator: {subject} Questioning")
    with col_header2:
        # Master Voice Toggle for the AfL Tab
        enable_voice = st.toggle("🔊 Voice Audio", value=True, key="afl_voice_toggle")
    with col_header3:
        if st.button(
            "🔄 Refresh session",
            key="afl_refresh_session",
            help="Clear the opening question, student answers and every remembered comment.",
            width="stretch",
        ):
            _reset_academic_afl_state()
            st.rerun()
        
    api_key = get_secret("GEMINI_API_KEY")
    if not api_key:
        st.error("⚠️ Gemini API Key missing.")
        return
    genai.configure(api_key=api_key)

    if "wb_answers" not in st.session_state: st.session_state.wb_answers = None
    if "wb_probe_selected" not in st.session_state: st.session_state.wb_probe_selected = None

    # --- 1. THE INPUT AREA ---
    st.markdown("### 1. Present the Material")
    teacher_name = st.text_input(
        "Your Title/Name (e.g., Mr. Smith, Miss, Sir):",
        value="Sir",
        key="afl_teacher_name",
    )
    teacher_question = st.text_area(
        "Ask the class your opening question:",
        key="afl_teacher_question",
    )
    uploaded_file = st.file_uploader(
        "Upload a resource (optional)",
        type=['png', 'jpg', 'jpeg'],
        key="afl_resource_upload",
    )
    
    if uploaded_file is not None:
        st.image(uploaded_file, caption="Class Resource", width="stretch")
    
    # --- 2. THE MODE SELECTOR ---
    st.markdown("---")
    st.markdown("### 2. Select Questioning Strategy")
    mode = st.radio("Strategy:", [
        "📝 Mini-Whiteboards (Whole Class)", 
        "🚪 Exit Tickets (Detailed)", 
        "🙋 Hands Up (Volunteers)", 
        "🎯 Cold Call (Interactive Probing)"
    ], horizontal=True, label_visibility="collapsed", key="afl_strategy")
    
    st.markdown("---")
    
    if not teacher_question:
        if st.session_state[_AFL_DISCUSSION_KEY]:
            _render_afl_discussion()
        st.info("👆 Please type an opening question above to begin.")
        return

    _render_afl_discussion()
    st.markdown("---")

    # --- MODE: MINI-WHITEBOARDS ---
    if mode == "📝 Mini-Whiteboards (Whole Class)":
        st.caption("Scans the whole room for quick, short-form answers. Click 'Probe' under a student to question their specific answer.")
        
        if st.session_state.wb_probe_selected:
            target_name = st.session_state.wb_probe_selected
            st.markdown(f"### 🗣️ Probing {target_name}'s Whiteboard Answer")

            raw_ans = st.session_state.wb_answers.get(target_name, "?")
            _record_opening_question(teacher_name, teacher_question)
            _append_afl_comment(
                "student",
                target_name,
                raw_ans,
                source="whiteboard",
                marker=f"whiteboard::{teacher_question.strip()}::{target_name}",
            )

            col_a, col_b = st.columns([1, 4])
            with col_a:
                display_student_photo(target_name, cohort)
                md_ans = str(raw_ans).replace("\n", "\n\n")
                
                with st.container(border=True):
                    st.markdown(f"<div style='text-align: center; font-size: 1.4rem; padding: 15px 0;'>\n\n{md_ans}\n\n</div>", unsafe_allow_html=True)
                
                if st.button("🔙 Back to Whiteboards", width="stretch"):
                    st.session_state.wb_probe_selected = None
                    st.rerun()
                    
            with col_b:
                if "latest_audio" in st.session_state:
                    st.audio(st.session_state["latest_audio"], format="audio/mp3", autoplay=True)
                    del st.session_state["latest_audio"]

                st.caption(
                    f"{target_name} can hear the remembered class discussion, including "
                    "other students' answers."
                )
                follow_up = st.chat_input(
                    f"Ask {target_name} to explain, comment on or improve an answer..."
                )
                if follow_up:
                    _append_afl_comment("teacher", teacher_name, follow_up)
                    
                    with st.spinner(f"{target_name} is reacting..."):
                        target_row = df[df["Full Name"] == target_name].iloc[0]

                        try:
                            reply_text, current_emotion = generate_discussion_reply(
                                target_name,
                                target_row,
                                cohort,
                                subject,
                                teacher_name,
                            )
                            _append_afl_comment("student", target_name, reply_text)
                            st.toast(f"Student Mood: {current_emotion.upper()} 🎭")
                            
                            if enable_voice:
                                student_voice_id = target_row.get("Voice_Name", "JBFqnCBsd6RMkjVDRZzb")
                                audio_bytes = get_elevenlabs_audio(
                                    reply_text,
                                    student_voice_id,
                                    cohort,
                                )
                                if audio_bytes:
                                    st.session_state["latest_audio"] = audio_bytes
                                    
                            st.rerun()
                                
                        except Exception as e:
                            st.error(f"Failed to generate response: {e}")
                            
        else:
            if st.session_state.wb_answers is None:
                if st.button("Show All Mini-Whiteboards", type="primary"):
                    with st.spinner("Students are scribbling on their boards..."):
                        instructions = "Write ONLY the absolute minimum factual or mathematical answer the student would scribble on a whiteboard (1 to 4 words max). Do not write full sentences. Do not include commentary. Be extremely brief. CRITICAL: Inject realistic, age-appropriate spelling and grammar mistakes, particularly for students with lower target grades, SEN, or EAL status."
                        answers = fetch_ai_answers(teacher_question, df, instructions, uploaded_file, cohort, subject, teacher_name, is_written=True)
                        
                    if answers:
                        reveal_text = st.empty()
                        for word in ["Three...", "Two...", "One...", "Show me!"]:
                            reveal_text.markdown(f"<h2 style='text-align: center; color: #E67E22;'>{word}</h2>", unsafe_allow_html=True)
                            time.sleep(0.7)
                        reveal_text.empty() 
                        
                        st.session_state.wb_answers = answers
                        st.rerun()
            else:
                st.markdown("---")
                num_cols = 5
                for i in range(0, len(df), num_cols):
                    cols = st.columns(num_cols)
                    for col, (_, row) in zip(cols, df.iloc[i : i + num_cols].iterrows()):
                        with col:
                            name = row.get("Full Name")
                            display_student_photo(name, cohort)
                            st.markdown(f"<div style='text-align: center; font-weight: bold; font-size: 13px; margin: 4px 0;'>{name}</div>", unsafe_allow_html=True)
                            
                            raw_ans = st.session_state.wb_answers.get(name, "?")
                            md_ans = str(raw_ans).replace("\n", "\n\n")
                            
                            with st.container(border=True):
                                st.markdown(f"<div style='text-align: center; font-size: 1.4rem; padding: 15px 0;'>\n\n{md_ans}\n\n</div>", unsafe_allow_html=True)
                            
                            if st.button(f"🗣️ Probe", key=f"probe_{name}", width="stretch"):
                                _record_opening_question(teacher_name, teacher_question)
                                _append_afl_comment(
                                    "student",
                                    name,
                                    raw_ans,
                                    source="whiteboard",
                                    marker=f"whiteboard::{teacher_question.strip()}::{name}",
                                )
                                st.session_state.wb_probe_selected = name
                                st.rerun()

    # --- MODE: EXIT TICKETS ---
    elif mode == "🚪 Exit Tickets (Detailed)":
        st.caption(
            "Collects a detailed paragraph from every student. Tickets remain available "
            "until you refresh the AfL session."
        )
        saved_ticket_set = st.session_state[_AFL_EXIT_ANSWERS_KEY]

        if saved_ticket_set is None and st.button("Collect Exit Tickets", type="primary"):
            with st.spinner("Students are writing their work (this may take a moment for a full class)..."):
                
                instructions = (
                    "Write EXACTLY what the student would write in their exercise book. "
                    "CRITICAL REALISM BY TARGET GRADE: You MUST scale the actual quality of the English, sentence structure, and vocabulary to their specific Target Grade.\n"
                    "- Target Grade 7-9: Flawless or near-perfect grammar. Highly articulate, structured, and fluent. No forced errors.\n"
                    "- Target Grade 4-6: Typical teenager. Mostly accurate, but might lack depth, use casual phrasing, or have occasional minor punctuation slips.\n"
                    "- Target Grade 1-3: Noticeably weak literacy. Use very basic vocabulary, short fragmented sentences, and struggle to articulate the 'why'. They should sound like a student with a low reading age. Inject realistic spelling errors (phonetic spelling of hard words) and crossed-out mistakes using Markdown strikethrough (~~like this~~).\n"
                    "DO NOT include any AI commentary or explanation. Output raw student work only."
                )
                
                answers = fetch_ai_answers(teacher_question, df, instructions, uploaded_file, cohort, subject, teacher_name, is_written=True)
                
                if answers:
                    st.session_state[_AFL_EXIT_ANSWERS_KEY] = {
                        "question": teacher_question,
                        "answers": answers,
                        "subject": subject,
                        "cohort": cohort,
                    }
                    _record_opening_question(teacher_name, teacher_question)
                    st.rerun()

        saved_ticket_set = st.session_state[_AFL_EXIT_ANSWERS_KEY]
        if saved_ticket_set:
            saved_question = saved_ticket_set["question"]
            answers = saved_ticket_set["answers"]
            saved_subject = saved_ticket_set["subject"]
            saved_cohort = saved_ticket_set["cohort"]

            st.success("✅ Exit tickets remembered until the AfL session is refreshed.")
            html_worksheet = create_printable_worksheet(
                saved_question,
                answers,
                df,
                saved_subject,
                saved_cohort,
            )
            st.download_button(
                label="🖨️ Download as Printable Worksheet",
                data=html_worksheet,
                file_name=f"{saved_cohort}_{saved_subject}_Full_Class_Marking_Exercise.html",
                mime="text/html",
                help="Downloads a formatted file. Open it in your browser and press Ctrl+P to print.",
                type="secondary",
                width="stretch",
            )
            st.markdown("---")
            st.markdown("### 📑 On-Screen Preview (Full Class)")
            for _, row in df.iterrows():
                name = row.get("Full Name")
                raw_ans = answers.get(name, "No ticket submitted.")
                st_ans = str(raw_ans).replace("\n", "\n\n")

                with st.expander(f"🎫 {name}'s Ticket"):
                    col1, col2 = st.columns([1, 5])
                    with col1:
                        display_student_photo(name, saved_cohort)
                    with col2:
                        st.markdown(st_ans)

    # --- MODE: HANDS UP ---
    elif mode == "🙋 Hands Up (Volunteers)":
        st.caption("A random number of students will volunteer. Select one to hear their answer and probe deeper.")
        
        if "hu_volunteers" not in st.session_state: st.session_state.hu_volunteers = []
        if "hu_selected" not in st.session_state: st.session_state.hu_selected = None

        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("🙋 Ask for Volunteers", type="primary", width="stretch"):
                max_volunteers = min(10, len(df))
                min_volunteers = min(3, max_volunteers)
                num_volunteers = random.randint(min_volunteers, max_volunteers)
                volunteer_df = df.sample(n=num_volunteers)
                st.session_state.hu_volunteers = volunteer_df["Full Name"].tolist()
                st.session_state.hu_selected = None
                st.rerun()
            if st.button("🔄 Clear Hands", width="stretch"):
                st.session_state.hu_volunteers = []
                st.session_state.hu_selected = None
                st.rerun()

        st.markdown("---")

        if st.session_state.hu_volunteers and not st.session_state.hu_selected:
            st.markdown("### 🖐️ Look who raised their hand:")
            vols = st.session_state.hu_volunteers
            
            for i in range(0, len(vols), 5):
                cols = st.columns(5)
                for idx, vol_name in enumerate(vols[i : i + 5]):
                    with cols[idx]:
                        display_student_photo(vol_name, cohort)
                        if st.button(f"Call on {vol_name}", key=f"btn_{vol_name}", width="stretch"):
                            st.session_state.hu_selected = vol_name
                            st.rerun()

        elif st.session_state.hu_selected:
            target_name = st.session_state.hu_selected
            st.markdown(f"### 🗣️ You called on {target_name}")
            interaction_token = _interaction_token(
                "hands-up",
                target_name,
                teacher_question,
            )

            col_a, col_b = st.columns([1, 4])
            with col_a:
                display_student_photo(target_name, cohort)
                if st.button("🔄 Pick Someone Else", width="stretch"):
                    st.session_state.hu_selected = None
                    st.rerun()

            with col_b:
                if "latest_audio" in st.session_state:
                    st.audio(st.session_state["latest_audio"], format="audio/mp3", autoplay=True)
                    del st.session_state["latest_audio"]

                if not _interaction_started(interaction_token):
                    with st.spinner(f"Waiting for {target_name} to respond..."):
                        _record_opening_question(teacher_name, teacher_question)
                        target_df = df[df["Full Name"] == target_name]
                        instructions = (
                            "Generate a spoken answer. They volunteered, so they feel "
                            "confident, but may confidently share a misconception. If "
                            "classmates have already contributed, naturally agree, challenge "
                            "or improve a relevant point rather than simply repeating it. "
                            "No commentary."
                        )
                        answers = fetch_ai_answers(
                            teacher_question,
                            target_df,
                            instructions,
                            uploaded_file,
                            cohort,
                            subject,
                            teacher_name,
                            discussion_history=_afl_transcript(),
                        )

                        if answers:
                            student_reply = answers.get(target_name, "...")
                            _append_afl_comment("student", target_name, student_reply)
                            _mark_interaction_started(interaction_token)

                            target_row = df[df["Full Name"] == target_name].iloc[0]

                            if enable_voice:
                                student_voice_id = target_row.get("Voice_Name", "JBFqnCBsd6RMkjVDRZzb")
                                audio_bytes = get_elevenlabs_audio(
                                    student_reply,
                                    student_voice_id,
                                    cohort,
                                )
                                if audio_bytes:
                                    st.session_state["latest_audio"] = audio_bytes
                                    
                            st.rerun()
                else:
                    st.caption(
                        f"Pick someone else to let them respond to {target_name}, or ask "
                        f"{target_name} to revisit any remembered answer."
                    )
                    follow_up = st.chat_input(
                        f"Ask {target_name} to explain, challenge or improve an answer..."
                    )
                    if follow_up:
                        _append_afl_comment("teacher", teacher_name, follow_up)
                        
                        with st.spinner(f"{target_name} is reacting..."):
                            target_row = df[df["Full Name"] == target_name].iloc[0]

                            try:
                                reply_text, current_emotion = generate_discussion_reply(
                                    target_name,
                                    target_row,
                                    cohort,
                                    subject,
                                    teacher_name,
                                )
                                _append_afl_comment("student", target_name, reply_text)
                                st.toast(f"Student Mood: {current_emotion.upper()} 🎭")
                                
                                if enable_voice:
                                    student_voice_id = target_row.get("Voice_Name", "JBFqnCBsd6RMkjVDRZzb")
                                    audio_bytes = get_elevenlabs_audio(
                                        reply_text,
                                        student_voice_id,
                                        cohort,
                                    )
                                    if audio_bytes:
                                        st.session_state["latest_audio"] = audio_bytes
                                        
                                st.rerun()
                            except Exception as exc:
                                st.error(f"Failed to generate response: {exc}")

    # --- MODE: COLD CALL (INTERACTIVE PROBING) ---
    elif mode == "🎯 Cold Call (Interactive Probing)":
        st.caption(
            "Choose different students in turn. Each student hears the full remembered "
            "discussion and can respond to or improve a classmate's answer."
        )
        target_name = st.selectbox(
            "Select student to Cold Call:",
            df["Full Name"].tolist(),
            key="afl_cold_call_student",
        )
        interaction_token = _interaction_token(
            "cold-call",
            target_name,
            teacher_question,
        )
            
        col1, col2 = st.columns([1, 4])
        with col1:
            display_student_photo(target_name, cohort)
            st.caption("Change the student above without losing any comments.")
                
        with col2:
            if "latest_audio" in st.session_state:
                st.audio(st.session_state["latest_audio"], format="audio/mp3", autoplay=True)
                del st.session_state["latest_audio"]
                
            if not _interaction_started(interaction_token):
                button_label = (
                    f"🗣️ Invite {target_name} into the discussion"
                    if st.session_state[_AFL_DISCUSSION_KEY]
                    else f"🗣️ Ask {target_name} the opening question"
                )
                if st.button(button_label, type="primary"):
                    with st.spinner(f"Waiting for {target_name} to respond..."):
                        _record_opening_question(teacher_name, teacher_question)
                        target_df = df[df["Full Name"] == target_name]
                        instructions = (
                            "Generate a spoken answer based on their profile. Include "
                            "hesitation or filler words ('Umm') if appropriate. If classmates "
                            "have already contributed, respond to a relevant idea by agreeing, "
                            "challenging, correcting or improving it. No commentary."
                        )
                        answers = fetch_ai_answers(
                            teacher_question,
                            target_df,
                            instructions,
                            uploaded_file,
                            cohort,
                            subject,
                            teacher_name,
                            discussion_history=_afl_transcript(),
                        )
                        
                        if answers:
                            student_reply = answers.get(target_name, "...")
                            _append_afl_comment("student", target_name, student_reply)
                            _mark_interaction_started(interaction_token)

                            target_row = df[df["Full Name"] == target_name].iloc[0]

                            if enable_voice:
                                student_voice_id = target_row.get("Voice_Name", "JBFqnCBsd6RMkjVDRZzb")
                                audio_bytes = get_elevenlabs_audio(
                                    student_reply,
                                    student_voice_id,
                                    cohort,
                                )
                                if audio_bytes:
                                    st.session_state["latest_audio"] = audio_bytes
                                    
                            st.rerun()
            else:
                follow_up = st.chat_input(
                    f"Ask {target_name} to explain, challenge or improve an answer..."
                )
                if follow_up:
                    _append_afl_comment("teacher", teacher_name, follow_up)
                    
                    with st.spinner(f"{target_name} is reacting..."):
                        target_row = df[df["Full Name"] == target_name].iloc[0]

                        try:
                            reply_text, current_emotion = generate_discussion_reply(
                                target_name,
                                target_row,
                                cohort,
                                subject,
                                teacher_name,
                            )
                            _append_afl_comment("student", target_name, reply_text)
                            st.toast(f"Student Mood: {current_emotion.upper()} 🎭")
                            
                            if enable_voice:
                                student_voice_id = target_row.get("Voice_Name", "JBFqnCBsd6RMkjVDRZzb")
                                audio_bytes = get_elevenlabs_audio(
                                    reply_text,
                                    student_voice_id,
                                    cohort,
                                )
                                if audio_bytes:
                                    st.session_state["latest_audio"] = audio_bytes
                                    
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Failed to generate response: {exc}")
