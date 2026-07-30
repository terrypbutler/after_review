import streamlit as st
from elevenlabs import VoiceSettings
from elevenlabs.client import ElevenLabs
import hashlib
import json
import time
import random
import re
from io import BytesIO
import wave
from PIL import Image
from config import REACTION_MODEL
from modules.app_shell import get_teacher_display_name
from modules.app_secrets import get_secret
from modules import gemini_client as genai
from modules.data_utils import get_ai_response_profile
from modules.photo_utils import display_student_photo
from modules.seating_plan_utils import (
    ensure_suggested_plan,
    order_dataframe_by_plan,
    plan_display_columns,
    seating_discussion_groups,
)
from modules.ui_components import render_seating_plan_overview

_AFL_DISCUSSION_KEY = "afl_discussion"
_AFL_STARTED_INTERACTIONS_KEY = "afl_started_interactions"
_AFL_EXIT_ANSWERS_KEY = "afl_exit_answers"
_AFL_PEER_FORMAT_VERSION = "long-conversations-v2"


def pcm_segments_to_wav(
    segments,
    sample_rate=24000,
    pause_ms=320,
):
    """Join signed 16-bit mono PCM clips into one sequential WAV conversation."""
    clean_segments = [bytes(segment) for segment in segments if segment]
    if not clean_segments:
        return None

    samples_per_pause = max(0, int(sample_rate * pause_ms / 1000))
    silence = b"\x00\x00" * samples_per_pause
    combined_pcm = silence.join(clean_segments)

    output = BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(combined_pcm)
    return output.getvalue()


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
    clean_teacher_name = " ".join(str(teacher_name or "").split()) or "Teacher"
    return _append_afl_comment(
        "teacher",
        clean_teacher_name,
        clean_question,
        marker=(
            f"opening-question::{clean_teacher_name.casefold()}::{clean_question}"
        ),
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


def _opening_afl_question():
    """Return the first teacher prompt retained in the current AfL session."""
    _ensure_afl_state()
    for comment in st.session_state[_AFL_DISCUSSION_KEY]:
        if comment.get("role") == "teacher":
            return str(comment.get("content", "")).strip()
    return ""


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
        if (
            key in reset_keys
            or str(key).startswith("probe_chat_")
            or str(key).startswith("afl_peer_")
        ):
            del st.session_state[key]


def generate_discussion_reply(target_name, target_row, cohort, subject, teacher_name):
    """Generate a student's response using the whole remembered class discussion."""
    response_profile = get_ai_response_profile(target_row, cohort, subject)
    transcript = _afl_transcript()
    question_context = _opening_afl_question() or transcript
    response_outcome = _response_outcome(
        target_row,
        question_context,
        subject,
    )
    outcome_guidance = _RESPONSE_OUTCOME_GUIDANCE[response_outcome]
    misconception_guidance = _SUBJECT_MISCONCEPTION_GUIDANCE.get(
        str(subject).strip().casefold(),
        "Use an authentic question-specific error from the subject.",
    )

    chat_prompt = f"""
    You are roleplaying as {target_name}, a {cohort} student.
    The subject is {subject}. The teacher must be addressed exactly as "{teacher_name}".
    Use this compact pupil response profile:
    {response_profile}

    Their underlying response state for this question is:
    {response_outcome.upper()} — {outcome_guidance}
    Relevant misconception guidance: {misconception_guidance}

    This is the whole-class discussion so far. It includes comments from the teacher
    and potentially several different students:
    {transcript}

    CRITICAL RULES:
    1. Respond as {target_name} to the teacher's latest comment or instruction. Keep it brief (1-2 sentences).
    2. Remember every earlier contribution. If asked about another student's answer,
       explicitly agree, disagree, correct, extend or improve it in a realistic way.
    3. Do not claim that another student's comment was your own.
       Never substitute "Sir", "Miss" or another title for "{teacher_name}" unless
       that is exactly the supplied teacher name/title.
    4. Match the student's likely attainment and needs. Do not automatically become
       correct just because the teacher probes. Reveal the pupil's thinking; self-correct
       only when the latest prompt or a classmate has supplied a genuinely useful scaffold.
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
    output_format="mp3_44100_96",
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
            output_format=output_format,
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


_RESPONSE_OUTCOME_GUIDANCE = {
    "secure": (
        "Give a correct, age-appropriate answer, but keep it like genuine pupil work: "
        "concise rather than polished or teacher-like."
    ),
    "partial": (
        "Show a correct starting idea but omit an important step, qualification, piece "
        "of evidence or explanation, so the answer does not fully meet the question."
    ),
    "misconception": (
        "Give a plausible, recognisable subject-specific misconception that a teacher "
        "could diagnose. It must be relevant to this exact question, not a random error."
    ),
    "slip": (
        "Use a mainly sound idea or method but include one realistic calculation, sign, "
        "unit, transcription, terminology or evidence-selection slip."
    ),
    "uncertain": (
        "Make a tentative, incomplete attempt. The pupil may hesitate or say they are "
        "not sure, but must still reveal enough thinking for the teacher to respond."
    ),
}

_SUBJECT_MISCONCEPTION_GUIDANCE = {
    "maths": (
        "Choose from question-relevant errors such as the wrong inverse operation, "
        "negative-sign or place-value confusion, operating on numerator and denominator "
        "incorrectly, confusing area with perimeter, order-of-operations errors, or "
        "missing/incorrect units."
    ),
    "english": (
        "Choose a question-relevant error such as retelling instead of analysing, an "
        "unsupported inference, misidentifying a method, selecting weak evidence, "
        "confusing speaker or viewpoint, or explaining effect too generally."
    ),
    "science": (
        "Choose a question-relevant everyday misconception, such as confusing mass and "
        "weight, heat and temperature, force and motion, energy stores and transfers, "
        "particles and substances, cells and organs, or independent and control variables."
    ),
}


def _first_number(value):
    """Return the first numeric value in a spreadsheet cell, if present."""
    text = str(value or "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _bounded_metric(row, columns):
    """Read a 0-100 pupil metric without treating missing data as zero."""
    value = get_flexible_text(row, columns, default="")
    number = _first_number(value)
    if number is None:
        return None
    return max(0.0, min(100.0, number))


def _grade_score(row, columns):
    """Normalise a 1-9 predicted grade to a 0-100 attainment estimate."""
    value = get_flexible_text(row, columns, default="")
    if not value:
        return None
    if str(value).strip().upper() == "B":
        return 22.0
    number = _first_number(value)
    if number is None:
        return None
    if 0 <= number <= 9:
        return max(0.0, min(100.0, number / 9.0 * 100.0))
    return None


def _ks2_score(row, columns):
    """Normalise a KS2 scaled score, retaining B as below expected level."""
    value = get_flexible_text(row, columns, default="")
    if not value:
        return None
    if str(value).strip().upper() == "B":
        return 22.0
    number = _first_number(value)
    if number is None:
        return None
    if 80 <= number <= 120:
        return max(0.0, min(100.0, (number - 80.0) / 40.0 * 100.0))
    return None


def _set_score(row, subject):
    """Use teaching set as a light fallback when no attainment grade is available."""
    subject_key = str(subject).strip().casefold()
    set_column = {
        "maths": "Maths Set",
        "english": "English Set",
        "science": "Science Set",
    }.get(subject_key)
    if not set_column:
        return None
    set_number = _first_number(get_flexible_text(row, [set_column], default=""))
    if set_number is None:
        return None
    return {
        1: 82.0,
        2: 68.0,
        3: 54.0,
        4: 41.0,
        5: 30.0,
    }.get(int(set_number), 45.0)


def _student_attainment_score(row, subject):
    """Estimate likely answer security from subject attainment and learning metrics."""
    subject_key = str(subject).strip().casefold()
    grade_columns = {
        "maths": ["Maths Predicted Grade", "Maths Target Grade"],
        "english": [
            "Eng Lang Predicted Grade",
            "Eng Lit Predicted Grade",
            "English Predicted Grade",
            "English Target Grade",
        ],
        "science": [
            "Sci 1 Predicted Grade",
            "Sci 2 Predicted Grade",
            "Science Predicted Grade",
            "Science Target Grade",
        ],
    }.get(subject_key, [])
    grade_columns += ["Projected Grade", "Predicted Grade", "Target Grade"]

    attainment_evidence = []
    grade = _grade_score(row, grade_columns)
    if grade is not None:
        attainment_evidence.append(grade)

    if subject_key == "english":
        ks2 = _ks2_score(
            row,
            ["KS2 Read", "KS2 Reading", "SATs Reading", "SAT's Reading"],
        )
    elif subject_key in {"maths", "science"}:
        ks2 = _ks2_score(
            row,
            ["KS2 Maths", "KS2 Math", "SATs Maths", "SAT's Maths"],
        )
    else:
        ks2 = None
    if ks2 is not None:
        attainment_evidence.append(ks2)

    set_score = _set_score(row, subject)
    if set_score is not None:
        attainment_evidence.append(set_score)

    confidence = _bounded_metric(row, ["Academic Confidence"])
    independence = _bounded_metric(row, ["Independence"])
    learning_metrics = [
        value for value in (confidence, independence) if value is not None
    ]

    attainment = (
        sum(attainment_evidence) / len(attainment_evidence)
        if attainment_evidence
        else 50.0
    )
    if not learning_metrics:
        return attainment

    learning_readiness = sum(learning_metrics) / len(learning_metrics)
    return 0.78 * attainment + 0.22 * learning_readiness


def _response_outcome(row, question, subject):
    """Choose a stable but varied response outcome for one pupil and question."""
    score = _student_attainment_score(row, subject)
    if score >= 75:
        weights = (
            ("secure", 0.48),
            ("partial", 0.24),
            ("misconception", 0.12),
            ("slip", 0.11),
            ("uncertain", 0.05),
        )
    elif score >= 55:
        weights = (
            ("secure", 0.31),
            ("partial", 0.28),
            ("misconception", 0.22),
            ("slip", 0.12),
            ("uncertain", 0.07),
        )
    elif score >= 35:
        weights = (
            ("secure", 0.18),
            ("partial", 0.27),
            ("misconception", 0.32),
            ("slip", 0.12),
            ("uncertain", 0.11),
        )
    else:
        weights = (
            ("secure", 0.10),
            ("partial", 0.23),
            ("misconception", 0.38),
            ("slip", 0.13),
            ("uncertain", 0.16),
        )

    name = get_flexible_text(row, ["Full Name"], default="Student")
    seed_text = f"{name}|{subject}|{str(question).strip()}".casefold()
    digest = hashlib.sha256(seed_text.encode("utf-8")).digest()
    roll = int.from_bytes(digest[:8], "big") / float(2**64)

    cumulative = 0.0
    for outcome, weight in weights:
        cumulative += weight
        if roll < cumulative:
            return outcome
    return weights[-1][0]


def build_response_calibration(question, student_subset, subject):
    """Assign an unlabelled, realistic mix of answer qualities to a pupil group."""
    plans = []
    for _, row in student_subset.iterrows():
        plans.append(
            {
                "name": str(row.get("Full Name", "Student")),
                "score": _student_attainment_score(row, subject),
                "outcome": _response_outcome(row, question, subject),
            }
        )

    if len(plans) >= 4:
        required_substantive_errors = max(1, (len(plans) + 3) // 4)
        substantive_errors = [
            plan
            for plan in plans
            if plan["outcome"] in {"misconception", "slip"}
        ]
        candidates = sorted(
            (
                plan
                for plan in plans
                if plan["outcome"] not in {"misconception", "slip"}
            ),
            key=lambda plan: (plan["score"], plan["name"].casefold()),
        )
        while len(substantive_errors) < required_substantive_errors and candidates:
            plan = candidates.pop(0)
            plan["outcome"] = (
                "misconception"
                if len(substantive_errors) % 3 != 2
                else "slip"
            )
            substantive_errors.append(plan)
    elif len(plans) >= 2 and all(
        plan["outcome"] == "secure" for plan in plans
    ):
        lowest_security = min(
            plans,
            key=lambda plan: (plan["score"], plan["name"].casefold()),
        )
        lowest_security["outcome"] = "partial"

    return plans


def _format_response_calibration(plans, subject):
    lines = []
    for plan in plans:
        guidance = _RESPONSE_OUTCOME_GUIDANCE[plan["outcome"]]
        lines.append(f"- {plan['name']}: {plan['outcome'].upper()} — {guidance}")

    subject_guidance = _SUBJECT_MISCONCEPTION_GUIDANCE.get(
        str(subject).strip().casefold(),
        (
            "Use an authentic question-specific error from the subject rather than a "
            "random factual mistake."
        ),
    )
    return "\n".join(lines), subject_guidance


_DOMINANT_DISCUSSION_TERMS = (
    "takes control",
    "takes the lead",
    "dominant",
    "monopolis",
    "interrupt",
    "answers for others",
)
_RELUCTANT_DISCUSSION_TERMS = (
    "reluctant",
    "hesitant",
    "quiet",
    "withdraw",
    "listener",
    "waits to be asked",
    "avoids contributing",
    "low confidence",
)
_OFF_TASK_DISCUSSION_TERMS = (
    "off task",
    "off-task",
    "distract",
    "chatty",
    "side conversation",
    "loses focus",
    "lose focus",
    "needs redirect",
    "needs re-direction",
    "low-level disruption",
    "avoidance",
    "restless",
    "silly",
    "socialis",
)


def _contains_discussion_term(text, terms):
    clean_text = str(text or "").casefold()
    return any(term in clean_text for term in terms)


def _peer_name_set(value):
    return {
        name.strip().casefold()
        for name in re.split(r"[;,\n]+", str(value or ""))
        if name.strip()
    }


def build_discussion_dynamics(participant_df, discussion_kind):
    """Turn spreadsheet behaviour signals into a varied conversation structure."""
    participant_names = {
        str(name).strip().casefold()
        for name in participant_df.get("Full Name", [])
        if str(name).strip()
    }
    pupils = []
    group_off_task_score = 0

    for _, row in participant_df.iterrows():
        name = str(row.get("Full Name", "Student")).strip()
        style = get_flexible_text(
            row,
            ["Peer Discussion Style"],
            default="",
        )
        barrier = get_flexible_text(
            row,
            ["Typical Learning Barrier", "Learning Barrier"],
            default="",
        )
        participation = _bounded_metric(row, ["Participation Level"])
        confidence = _bounded_metric(row, ["Academic Confidence"])
        independence = _bounded_metric(row, ["Independence"])

        combined_behaviour = f"{style} | {barrier}"
        explicitly_dominant = _contains_discussion_term(
            combined_behaviour,
            _DOMINANT_DISCUSSION_TERMS,
        )
        explicitly_reluctant = _contains_discussion_term(
            combined_behaviour,
            _RELUCTANT_DISCUSSION_TERMS,
        )

        if explicitly_dominant or (
            participation is not None
            and confidence is not None
            and participation >= 88
            and confidence >= 80
            and (independence is None or independence < 60)
        ):
            pattern = "monopolises"
            guidance = (
                "Take substantially more airtime than the others. Return repeatedly, "
                "steer the discussion, interrupt or answer for someone where natural. "
                "This does not make the pupil automatically correct."
            )
        elif explicitly_reluctant or (
            (participation is not None and participation <= 30)
            or (confidence is not None and confidence <= 28)
        ):
            pattern = "reluctant"
            guidance = (
                "Be reluctant to share. Initially defer, give a fragment, say 'you go', "
                "or need a direct invitation. Contribute only one or two short turns and "
                "do not suddenly become fluent."
            )
        else:
            pattern = "balanced"
            guidance = (
                "Contribute naturally without equal-turn choreography. Respond to a peer, "
                "and speak again only when the discussion gives a reason."
            )

        preferred_peers = _peer_name_set(
            get_flexible_text(row, ["Preferred Peers"], default="")
        )
        seated_with_preferred_peer = bool(
            (preferred_peers & participant_names) - {name.casefold()}
        )
        explicit_off_task = _contains_discussion_term(
            combined_behaviour,
            _OFF_TASK_DISCUSSION_TERMS,
        )

        pupil_off_task_score = 0
        if explicit_off_task:
            pupil_off_task_score += 4
        if independence is not None and independence < 38:
            pupil_off_task_score += 2
        if seated_with_preferred_peer:
            pupil_off_task_score += 1
        if pattern == "monopolises" and participation is not None and participation >= 80:
            pupil_off_task_score += 1
        group_off_task_score = max(group_off_task_score, pupil_off_task_score)

        signal_parts = []
        if style:
            signal_parts.append(f"recorded style: {style}")
        for label, value in (
            ("participation", participation),
            ("confidence", confidence),
            ("independence", independence),
        ):
            if value is not None:
                signal_parts.append(f"{label} {value:.0f}/100")
        if seated_with_preferred_peer:
            signal_parts.append("seated with a preferred peer")

        pupils.append(
            {
                "name": name,
                "pattern": pattern,
                "guidance": guidance,
                "signals": "; ".join(signal_parts) or "no strong discussion signal",
            }
        )

    if group_off_task_score >= 4:
        off_task_level = "likely"
        off_task_guidance = (
            "Include one to three brief, harmless off-task turns. Use ordinary school "
            "small talk or an interest already present in the compact profile; never use "
            "safeguarding or sensitive home information. Show a believable attempt to "
            "return to the task, but the group need not reach a polished conclusion."
        )
    elif group_off_task_score >= 2:
        off_task_level = "possible"
        off_task_guidance = (
            "Include one short, harmless off-task detour before a pupil redirects the "
            "conversation. Do not use private home or safeguarding information."
        )
    else:
        off_task_level = "unlikely"
        off_task_guidance = (
            "Keep this exchange on task; do not force an off-task interlude when the "
            "spreadsheet behaviour signals do not support one."
        )

    is_pair = discussion_kind == "turn_and_talk"
    minimum_turns = 5 if is_pair else 7
    maximum_turns = 12 if is_pair else 16
    if any(pupil["pattern"] == "monopolises" for pupil in pupils):
        maximum_turns += 2
    if off_task_level == "likely":
        maximum_turns += 2
    maximum_turns = min(maximum_turns, 18)

    return {
        "pupils": pupils,
        "off_task_level": off_task_level,
        "off_task_guidance": off_task_guidance,
        "minimum_turns": minimum_turns,
        "maximum_turns": maximum_turns,
    }


def _format_discussion_dynamics(dynamics):
    pupil_lines = [
        (
            f"- {pupil['name']}: {pupil['pattern'].upper()} "
            f"({pupil['signals']}). {pupil['guidance']}"
        )
        for pupil in dynamics["pupils"]
    ]
    return "\n".join(pupil_lines)


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
    response_plans = build_response_calibration(
        question,
        student_subset,
        subject,
    )
    calibration_text, misconception_guidance = _format_response_calibration(
        response_plans,
        subject,
    )
    
    if is_written:
        address_rule = "4. Written Work: DO NOT use the teacher's name or titles like 'Sir' or 'Miss' in the response. It must read entirely like an exercise book or whiteboard."
    else:
        address_rule = (
            f"4. Teacher Address: The exact teacher name/title is '{teacher_name}'. "
            f"Students may use '{teacher_name}' naturally, but MUST NOT replace it "
            "with 'Sir', 'Miss' or another name/title."
        )
    
    prompt = f"""
    A trainee teacher whose exact name/title is '{teacher_name}' is conducting a
    {subject} lesson for a class of {cohort} students (approximate age: {age_context}).
    The teacher has asked the class: "{question}"
    
    Here are the compact, privacy-minimised response profiles for the students answering:
    {profiles_text}

    MANDATORY RESPONSE CALIBRATION FOR THIS ATTEMPT:
    {calibration_text}

    Misconceptions in {subject}: {misconception_guidance}
    
    {instructions}

    Remembered whole-class discussion:
    {discussion_history or "No students have contributed yet."}
    
    CRITICAL PEDAGOGICAL CONSTRAINTS:
    1. Ability Match: Scale vocabulary, accuracy, length, and depth to the compact profile.
    2. Follow each pupil's assigned response calibration exactly. Privately solve or
       analyse the question first, then construct the assigned outcome. Do not label,
       diagnose or explain the error in the pupil's answer.
    3. Participation Match: Use the pupil's confidence, participation, processing and discussion style; do not invent private background information.
    {address_rule}
    5. Math Formatting: Make maths look like real maths. DO NOT use raw carets (like r^2). You MUST use Unicode superscripts (e.g., r², x³, y₁) and symbols (π, √, ÷, ×, ±). For complex equations, use LaTeX wrapped in single `$` (e.g., `$x = \\frac{{1}}{{2}}$`).
    6. Layout: If the answer involves multiple steps of calculation, you MUST put each step on a new line using a newline character (\\n).
    
    CRITICAL TECHNICAL RULES:
    - Return ONLY a valid JSON dictionary where keys are exact student names and values are their answers.
    - A misconception must be plausible enough that a teacher can probe it. Do not use
      spelling or grammar alone as the misconception, and do not make errors silly.
    - Do not silently repair a MISCONCEPTION, SLIP, PARTIAL or UNCERTAIN response into a
      fully correct answer. Variation across the class is intentional.
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


def generate_peer_discussion(
    question,
    participant_df,
    cohort,
    subject,
    teacher_name,
    discussion_kind,
    uploaded_file=None,
):
    """Simulate a seating-based pupil conversation and its class feedback."""
    participant_names = participant_df["Full Name"].astype(str).tolist()
    profiles = [
        (
            f"- {row.get('Full Name')}: "
            f"{get_ai_response_profile(row, cohort, subject)}"
        )
        for _, row in participant_df.iterrows()
    ]
    discussion_dynamics = build_discussion_dynamics(
        participant_df,
        discussion_kind,
    )
    dynamics_text = _format_discussion_dynamics(discussion_dynamics)
    minimum_turns = discussion_dynamics["minimum_turns"]
    maximum_turns = discussion_dynamics["maximum_turns"]
    target_turns = random.randint(minimum_turns, maximum_turns)
    response_plans = build_response_calibration(
        question,
        participant_df,
        subject,
    )
    calibration_text, misconception_guidance = _format_response_calibration(
        response_plans,
        subject,
    )
    is_pair = discussion_kind == "turn_and_talk"
    format_description = (
        "an adjacent pair completing a brief turn-and-talk"
        if is_pair
        else "a table group discussing the question together"
    )

    prompt = f"""
    **[FICTIONAL SCENARIO FOR TEACHER TRAINING - ALL DATA IS MOCK/SYNTHETIC]**
    A {cohort} {subject} class has been asked: "{question}"
    The teacher must be addressed exactly as "{teacher_name}". Do not replace this
    with "Sir", "Miss" or another title.

    Simulate {format_description}. The pupils are:
    {chr(10).join(profiles)}

    MANDATORY STARTING RESPONSE STATES:
    {calibration_text}
    Misconceptions in {subject}: {misconception_guidance}

    MANDATORY DISCUSSION DYNAMICS FROM THE SPREADSHEET:
    {dynamics_text}

    Group off-task likelihood: {discussion_dynamics["off_task_level"].upper()}.
    {discussion_dynamics["off_task_guidance"]}

    Remembered whole-class discussion before they start:
    {_afl_transcript() or "No earlier contributions."}

    PEDAGOGICAL RULES:
    1. Produce exactly {target_turns} short conversational turns for this exchange.
       This target was selected from a natural range of {minimum_turns} to
       {maximum_turns}; do not stop at four and do not distribute turns evenly.
       Every pupil must be represented at least once using their exact name, although
       a reluctant pupil's contribution may only be a refusal, fragment or prompted reply.
    2. Make it a real exchange: pupils can agree, question, correct, extend, interrupt,
       defer or challenge one another according to their assigned dynamics. A pupil
       marked MONOPOLISES should take visibly more turns than their peers.
    3. Match each pupil's attainment, confidence, processing and discussion style, and
       follow their assigned starting state. Do not label mistakes in the conversation.
       Another pupil may notice, question or correct an error, but they should not all
       jump immediately to a polished correct conclusion.
    4. Do not introduce the teacher as a speaker and do not invent private background.
    5. Keep each turn to one or two natural spoken sentences.
    6. Create a concise "feedback" statement in the pupils' collective voice that
       could be shared with the whole class. It should state their conclusion and
       preserve any important uncertainty; do not describe the hidden conversation.

    Return ONLY this JSON structure:
    {{
      "turns": [
        {{"speaker": "Exact pupil name", "dialogue": "What they say"}}
      ],
      "feedback": "We think..."
    }}
    """

    allowed_names = set(participant_names)

    def clean_turns(payload):
        cleaned = []
        for turn in payload.get("turns", []):
            speaker = str(turn.get("speaker", "")).strip()
            dialogue = str(turn.get("dialogue", "")).strip()
            if speaker in allowed_names and dialogue:
                cleaned.append({"speaker": speaker, "dialogue": dialogue})
        return cleaned

    for attempt in range(2):
        try:
            model = genai.GenerativeModel(REACTION_MODEL)
            contents = [prompt]
            if uploaded_file is not None:
                uploaded_file.seek(0)
                contents.append(Image.open(uploaded_file).copy())
            response = model.generate_content(
                contents,
                generation_config={"response_mime_type": "application/json"},
            )
            raw_text = response.text.replace("```json", "").replace("```", "")
            ai_data = json.loads(raw_text.strip())

            turns = clean_turns(ai_data)
            feedback = str(ai_data.get("feedback", "")).strip()
            continuation_count = 0

            while len(turns) < target_turns and continuation_count < 2:
                turns_needed = target_turns - len(turns)
                existing_transcript = "\n".join(
                    f"{turn['speaker']}: {turn['dialogue']}"
                    for turn in turns
                )
                continuation_prompt = f"""
                {prompt}

                IMPORTANT CONTINUATION:
                The first generation stopped too early after {len(turns)} turns.
                Here is the private conversation so far:
                {existing_transcript}

                Continue from that exact point with {turns_needed} NEW turns. Do not
                restart, repeat or summarise the existing turns. Preserve the assigned
                reluctance, monopolising and off-task dynamics. Return only:
                {{
                  "turns": [
                    {{"speaker": "Exact pupil name", "dialogue": "New dialogue only"}}
                  ],
                  "feedback": "Updated collective feedback after the full discussion"
                }}
                """
                continuation_response = model.generate_content(
                    continuation_prompt,
                    generation_config={"response_mime_type": "application/json"},
                )
                continuation_raw = (
                    continuation_response.text
                    .replace("```json", "")
                    .replace("```", "")
                )
                continuation_data = json.loads(continuation_raw.strip())
                extra_turns = clean_turns(continuation_data)
                if not extra_turns:
                    break
                turns.extend(extra_turns[:turns_needed])
                updated_feedback = str(
                    continuation_data.get("feedback", "")
                ).strip()
                if updated_feedback:
                    feedback = updated_feedback
                continuation_count += 1

            bounded_turns = turns[:target_turns]
            represented_names = {turn["speaker"] for turn in bounded_turns}
            if (
                minimum_turns <= len(bounded_turns) <= target_turns
                and feedback
                and represented_names == allowed_names
            ):
                return {
                    "turns": bounded_turns,
                    "feedback": feedback,
                    "target_turns": target_turns,
                }
        except Exception as exc:
            if attempt == 1:
                st.error(f"Could not generate the pupil discussion: {exc}")

    return {"turns": [], "feedback": ""}


def _remember_peer_result_for_class(
    result_kind,
    speaker_label,
    feedback,
    discussion_kind,
    result_context,
):
    """Keep listen-in turns private; remember only feedback spoken to the class."""
    if result_kind != "feedback":
        return False
    return _append_afl_comment(
        "student",
        speaker_label,
        feedback,
        source="peer-discussion",
        marker=f"{discussion_kind}::{result_context}::feedback",
    )


def _render_peer_discussion_strategy(
    df,
    cohort,
    subject,
    teacher_name,
    teacher_question,
    uploaded_file,
    enable_voice,
    seating_plan,
    discussion_kind,
):
    """Render Turn and Talk or table discussion controls and results."""
    is_pair = discussion_kind == "turn_and_talk"
    group_size = 2 if is_pair else 4
    groups = seating_discussion_groups(seating_plan, df, group_size)
    strategy_title = "Turn and Talk" if is_pair else "Group Discussion"

    st.markdown(f"### {strategy_title}")
    st.caption(
        (
            "Select two pupils who are seated next to one another."
            if is_pair
            else "Select a saved table group."
        )
        + " Pupils in the selected pair/table can hear one another, but the rest "
        "of the class cannot hear this private exchange. Only 'Feedback to class' "
        "enters the shared class discussion."
    )

    if not groups:
        st.warning(
            "No suitable seated group is available. Open Seating Plan, select the "
            "same class and create or adjust its plan."
        )
        return

    labels = [group["label"] for group in groups]
    selected_label = st.selectbox(
        "Choose seated pupils",
        labels,
        key=f"afl_peer_{discussion_kind}_selection",
    )
    selected_group = next(
        group for group in groups if group["label"] == selected_label
    )
    participant_names = selected_group["students"]
    participant_df = df[
        df["Full Name"].astype(str).isin(participant_names)
    ].copy()
    participant_df["_discussion_order"] = participant_df["Full Name"].map(
        {name: index for index, name in enumerate(participant_names)}
    )
    participant_df = participant_df.sort_values("_discussion_order").drop(
        columns="_discussion_order"
    )

    photo_columns = st.columns(len(participant_names))
    for column, name in zip(photo_columns, participant_names):
        with column:
            display_student_photo(name, cohort)
            st.markdown(f"**{name}**")
    st.caption(selected_group["location"])

    result_key = f"afl_peer_{discussion_kind}_result"
    result_context = (
        f"{_AFL_PEER_FORMAT_VERSION}|{selected_label}|{subject}|"
        f"{teacher_question.strip()}|"
        f"{st.session_state.get('afl_class_context', '')}"
    )
    listen_column, feedback_column = st.columns(2)

    with listen_column:
        listen_clicked = st.button(
            "🔊 Listen to conversation",
            type="primary",
            width="stretch",
            key=f"afl_peer_{discussion_kind}_listen",
        )
    with feedback_column:
        feedback_clicked = st.button(
            "📣 Feedback to class",
            width="stretch",
            key=f"afl_peer_{discussion_kind}_feedback",
            help=(
                "The discussion is simulated, but only the pupils' collective "
                "summary is shown."
            ),
        )

    if listen_clicked or feedback_clicked:
        action_text = "conversation" if listen_clicked else "private discussion"
        with st.spinner(f"Simulating the pupils' {action_text}..."):
            discussion = generate_peer_discussion(
                teacher_question,
                participant_df,
                cohort,
                subject,
                teacher_name,
                discussion_kind,
                uploaded_file,
            )

        if discussion["turns"] and discussion["feedback"]:
            if listen_clicked:
                turns_with_audio = []
                voice_available = bool(get_secret("ELEVENLABS_API_KEY"))
                if enable_voice and not voice_available:
                    st.warning(
                        "The conversation transcript is ready, but the ElevenLabs "
                        "key is unavailable, so voice audio could not be created."
                    )

                if enable_voice and voice_available:
                    pcm_segments = []
                    with st.spinner("Creating the pupils' voices..."):
                        for turn in discussion["turns"]:
                            speaker_rows = participant_df[
                                participant_df["Full Name"] == turn["speaker"]
                            ]
                            audio_bytes = None
                            if not speaker_rows.empty:
                                voice_id = get_flexible_text(
                                    speaker_rows.iloc[0],
                                    ["Voice_Name", "Voice ID", "Voice_ID"],
                                    "JBFqnCBsd6RMkjVDRZzb",
                                )
                                audio_bytes = get_elevenlabs_audio(
                                    turn["dialogue"],
                                    voice_id,
                                    cohort,
                                    output_format="pcm_24000",
                                )
                                if audio_bytes:
                                    pcm_segments.append(audio_bytes)
                            turns_with_audio.append(
                                {**turn, "audio": None}
                            )
                    conversation_audio = pcm_segments_to_wav(pcm_segments)
                else:
                    turns_with_audio = [
                        {**turn, "audio": None}
                        for turn in discussion["turns"]
                    ]
                    conversation_audio = None

                st.session_state[result_key] = {
                    "context": result_context,
                    "kind": "conversation",
                    "turns": turns_with_audio,
                    "feedback": discussion["feedback"],
                    "conversation_audio": conversation_audio,
                    "autoplay": bool(conversation_audio),
                }
                _remember_peer_result_for_class(
                    "conversation",
                    f"{selected_group['location']} feedback",
                    discussion["feedback"],
                    discussion_kind,
                    result_context,
                )
            else:
                # Deliberately discard the private turns so only feedback is shared.
                st.session_state[result_key] = {
                    "context": result_context,
                    "kind": "feedback",
                    "feedback": discussion["feedback"],
                }
                _remember_peer_result_for_class(
                    "feedback",
                    f"{selected_group['location']} feedback",
                    discussion["feedback"],
                    discussion_kind,
                    result_context,
                )

    result = st.session_state.get(result_key)
    if not result or result.get("context") != result_context:
        return

    st.markdown("---")
    if result["kind"] == "conversation":
        st.markdown("#### Private conversation")
        st.caption(
            "You are listening in. Other pairs and tables cannot hear these turns, "
            "and they have not been added to the shared class discussion."
        )
        st.caption(f"{len(result['turns'])} conversational turns generated.")
        if result.get("conversation_audio"):
            should_autoplay = bool(result.get("autoplay"))
            st.audio(
                result["conversation_audio"],
                format="audio/wav",
                autoplay=should_autoplay,
            )
            result["autoplay"] = False
        for turn in result["turns"]:
            with st.container(border=True):
                st.markdown(f"**{turn['speaker']}**")
                st.write(turn["dialogue"])
        st.caption(f"Possible class feedback: {result['feedback']}")
    else:
        st.markdown("#### Feedback shared with the class")
        st.success(result["feedback"])


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
    if "seating_plans" not in st.session_state:
        st.session_state.seating_plans = {}
    plan_key, seating_plan, plan_created = ensure_suggested_plan(
        st.session_state.seating_plans,
        df,
        cohort,
    )
    teacher_name = get_teacher_display_name()
    class_context = f"{plan_key}|{subject}|{teacher_name.casefold()}"
    previous_context = st.session_state.get("afl_class_context")
    if previous_context and previous_context != class_context:
        _reset_academic_afl_state()
    st.session_state.afl_class_context = class_context
    df = order_dataframe_by_plan(df, seating_plan)

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

    if plan_created:
        st.info(
            "A suggested seating plan was created from the spreadsheet relationship "
            "data. You can adjust it on the Seating Plan page."
        )
    render_seating_plan_overview(seating_plan, df, "Academic AfL")

    api_key = get_secret("GEMINI_API_KEY")
    if not api_key:
        st.error("⚠️ Gemini API Key missing.")
        return
    genai.configure(api_key=api_key)

    if "wb_answers" not in st.session_state: st.session_state.wb_answers = None
    if "wb_probe_selected" not in st.session_state: st.session_state.wb_probe_selected = None

    # --- 1. THE INPUT AREA ---
    st.markdown("### 1. Present the Material")
    st.caption(
        f"Teacher name/title: **{teacher_name}** · Change this using the shared "
        "sidebar field."
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
        "🗣️ Turn and Talk",
        "👥 Group Discussion",
        "🚪 Exit Tickets (Detailed)",
        "🙋 Hands Up (Volunteers)",
        "🎯 Cold Call (Interactive Probing)",
    ], horizontal=True, label_visibility="collapsed", key="afl_strategy")
    st.caption(
        "Response realism is active: pupils may give secure, partial or uncertain "
        "answers and may reveal common subject misconceptions. Errors are deliberately "
        "left unlabelled for you to diagnose and probe."
    )
    
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
                num_cols = plan_display_columns(seating_plan)
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
                    "- Target Grade 7-9: Usually controlled grammar and more articulate, structured writing, but the assigned response may still contain a conceptual error, omission or slip.\n"
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

    # --- MODE: TURN AND TALK ---
    elif mode == "🗣️ Turn and Talk":
        _render_peer_discussion_strategy(
            df,
            cohort,
            subject,
            teacher_name,
            teacher_question,
            uploaded_file,
            enable_voice,
            seating_plan,
            "turn_and_talk",
        )

    # --- MODE: GROUP DISCUSSION ---
    elif mode == "👥 Group Discussion":
        _render_peer_discussion_strategy(
            df,
            cohort,
            subject,
            teacher_name,
            teacher_question,
            uploaded_file,
            enable_voice,
            seating_plan,
            "group_discussion",
        )

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
