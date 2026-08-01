import streamlit as st
import json
import random
import re
from PIL import Image
from config import REACTION_MODEL
from modules.app_shell import (
    get_teacher_address_instruction,
    get_teacher_address_options,
    get_teacher_display_name,
)
from modules import ai_client as genai
from modules.data_utils import get_ai_response_profile
from modules.photo_utils import display_student_photo
from modules.seating_plan_utils import (
    ensure_suggested_plan,
    order_dataframe_by_plan,
    plan_display_columns,
)
from modules.ui_components import render_seating_plan_overview

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


def _observation_metric(row, possible_names, default=50.0):
    text = get_flexible_text(row, possible_names)
    match = re.search(r"-?\d+(?:\.\d+)?", str(text))
    if not match:
        return float(default)
    try:
        return max(0.0, min(100.0, float(match.group(0))))
    except ValueError:
        return float(default)


def _has_observation_signal(row, possible_names, terms):
    text = " | ".join(
        get_flexible_text(row, [column])
        for column in possible_names
    ).casefold()
    return any(term in text for term in terms)


def build_student_observation_state(row, rng=random):
    """Create a work-ready starting state from non-sensitive spreadsheet fields."""
    participation = _observation_metric(row, ["Participation Level"])
    confidence = _observation_metric(row, ["Academic Confidence"])
    independence = _observation_metric(row, ["Independence"])
    processing_speed = _observation_metric(row, ["Processing Speed"])

    motivation = (
        50
        + 0.16 * participation
        + 0.12 * confidence
        + 0.10 * independence
        + rng.randint(-5, 5)
    )
    if _has_observation_signal(
        row,
        ["Typical Learning Barrier", "Peer Discussion Style"],
        ("low motivation", "task avoidance", "refuses", "disengage"),
    ):
        motivation -= 8

    decay_rate = (
        2
        + (100 - independence) / 28
        + (100 - processing_speed) / 55
    )
    if _has_observation_signal(
        row,
        ["Typical Learning Barrier", "Peer Discussion Style"],
        ("distract", "loses focus", "off task", "off-task", "restless"),
    ):
        decay_rate += 1.5

    work_rate = 0.72 + processing_speed / 220 + independence / 300

    starting_motivation = int(max(38, min(92, round(motivation))))
    return {
        "motivation": starting_motivation,
        "initial_motivation": starting_motivation,
        "progress": 0,
        "decay_rate": int(max(2, min(9, round(decay_rate)))),
        "work_rate": max(0.65, min(1.45, work_rate)),
        "participation": participation,
        "confidence": confidence,
        "independence": independence,
        "processing_speed": processing_speed,
        "current_event": None,
        "current_event_kind": None,
        "last_toilet_minute": None,
        "work_questions": 0,
        "interventions": 0,
        "positive_interventions": 0,
    }


def _weighted_observation_sample(candidates, count, rng=random):
    """Select weighted candidates without allowing duplicate events."""
    if count <= 0 or not candidates:
        return []
    ranked = sorted(
        candidates,
        key=lambda item: rng.random() ** (1.0 / max(0.1, item[1])),
        reverse=True,
    )
    return [name for name, _weight in ranked[:count]]


def assign_classroom_events(
    active_names,
    df,
    student_states,
    current_minute,
    rng=random,
):
    """Allocate rare interruptions and frequent work questions at class level."""
    row_lookup = {
        str(row.get("Full Name")): row
        for _, row in df.iterrows()
    }
    eligible_names = [
        name
        for name in active_names
        if name in row_lookup
        and name in student_states
        and student_states[name].get("progress", 0) < 100
    ]
    if not eligible_names:
        return {}

    events = {}
    question_candidates = []
    for name in eligible_names:
        row = row_lookup[name]
        stats = student_states[name]
        question_weight = 1.0
        question_weight += max(0.0, (58 - stats.get("confidence", 50)) / 18)
        question_weight += max(
            0.0,
            (58 - stats.get("processing_speed", 50)) / 20,
        )
        question_weight += max(
            0.0,
            (55 - stats.get("independence", 50)) / 24,
        )
        if _has_observation_signal(
            row,
            ["Typical Learning Barrier", "Helpful Scaffold", "Current Learning Target"],
            (
                "reassurance",
                "clarif",
                "instruction",
                "next step",
                "ask",
                "check",
                "uncertain",
            ),
        ):
            question_weight += 2.0
        if stats.get("participation", 50) < 28:
            question_weight *= 0.65
        question_candidates.append((name, question_weight))

    question_count = max(
        1,
        min(3, int(len(eligible_names) * 0.08 + 0.5)),
    )
    question_prompts = (
        "You have a specific question about how to complete the next part of the work.",
        "You want the teacher to check whether your method or interpretation is on the right track.",
        "You need clarification of one instruction before you can continue confidently.",
        "You have noticed something in the task and want to ask a relevant follow-up question.",
    )
    for name in _weighted_observation_sample(
        question_candidates,
        question_count,
        rng,
    ):
        events[name] = {
            "kind": "work_question",
            "context": rng.choice(question_prompts),
        }

    # Toilet requests are a rare whole-class event, not a 5% roll per pupil.
    if rng.randint(1, 100) <= 3:
        toilet_candidates = [
            name
            for name in eligible_names
            if name not in events
            and (
                student_states[name].get("last_toilet_minute") is None
                or current_minute
                - student_states[name].get("last_toilet_minute", 0)
                >= 60
            )
        ]
        if toilet_candidates:
            chosen = rng.choice(toilet_candidates)
            events[chosen] = {
                "kind": "toilet",
                "context": "You need to ask to go to the toilet.",
            }
            student_states[chosen]["last_toilet_minute"] = current_minute

    # Peer complaints are capped at one and require recorded distraction signals.
    if rng.randint(1, 100) <= 6:
        peer_candidates = []
        for name in eligible_names:
            if name in events or student_states[name].get("motivation", 100) >= 48:
                continue
            row = row_lookup[name]
            if _has_observation_signal(
                row,
                ["Typical Learning Barrier", "Peer Discussion Style"],
                (
                    "distract",
                    "chatty",
                    "off task",
                    "off-task",
                    "side conversation",
                    "socialis",
                ),
            ):
                peer_candidates.append(name)
        if peer_candidates:
            chosen = rng.choice(peer_candidates)
            events[chosen] = {
                "kind": "peer_distraction",
                "context": (
                    "A nearby pupil has briefly distracted you and you want help "
                    "returning to the work."
                ),
            }

    return events


def _engagement_delay_minutes(entry):
    if not entry:
        return None
    time_value = str(entry.get("time", "")).strip()
    if not time_value or time_value.casefold() == "failed":
        return None
    match = re.match(r"(\d+):(\d+)", time_value)
    if not match:
        return None
    return int(match.group(1)) + int(match.group(2)) / 60.0


def build_learning_summary(
    active_names,
    student_states,
    engagement_log,
    live_observations,
    elapsed_minutes,
    planned_minutes,
    task,
):
    """Summarise generated rehearsal signals when the observed class stops."""
    pupils = [
        name
        for name in active_names
        if name in student_states
    ]
    if not pupils:
        return None

    progress_values = [
        float(student_states[name].get("progress", 0))
        for name in pupils
    ]
    motivation_values = [
        float(student_states[name].get("motivation", 0))
        for name in pupils
    ]
    average_progress = round(sum(progress_values) / len(progress_values))
    average_motivation = round(sum(motivation_values) / len(motivation_values))

    bands = {
        "substantial": sum(value >= 75 for value in progress_values),
        "secure": sum(50 <= value < 75 for value in progress_values),
        "developing": sum(25 <= value < 50 for value in progress_values),
        "limited": sum(value < 25 for value in progress_values),
    }

    failed_starts = 0
    delayed_starts = 0
    for name in pupils:
        entry = (engagement_log or {}).get(name, {})
        if str(entry.get("time", "")).casefold() == "failed":
            failed_starts += 1
            continue
        delay = _engagement_delay_minutes(entry)
        if delay is not None and delay >= 1:
            delayed_starts += 1

    total_questions = sum(
        int(student_states[name].get("work_questions", 0))
        for name in pupils
    )
    total_interventions = sum(
        int(student_states[name].get("interventions", 0))
        for name in pupils
    )

    gap_themes = []
    if bands["limited"] or bands["developing"]:
        gap_themes.append(
            f"{bands['limited'] + bands['developing']} pupils completed less than "
            "half of the expected task, suggesting a need to revisit access, "
            "understanding or independent application."
        )
    if total_questions:
        gap_themes.append(
            f"{total_questions} work-related questions were raised; check whether "
            "instructions, modelling or the next step need clarifying."
        )
    if failed_starts or delayed_starts:
        gap_themes.append(
            f"{failed_starts} pupils did not establish a start and {delayed_starts} "
            "started after the first minute; routines or task entry may need attention."
        )
    if average_motivation < 50:
        gap_themes.append(
            "The generated final class drive was low. Rehearse how you would check "
            "whether sustained attention is limiting access to the task."
        )
    if not gap_themes:
        gap_themes.append(
            "No broad engagement gap was evident; use the individual follow-up list "
            "to check smaller misconceptions or incomplete explanations."
        )

    ranked = sorted(
        pupils,
        key=lambda name: (
            student_states[name].get("progress", 0),
            student_states[name].get("motivation", 0),
        ),
        reverse=True,
    )
    standouts = []
    for name in ranked[:3]:
        stats = student_states[name]
        reasons = [f"{stats.get('progress', 0):.0f}% task progress"]
        motivation_change = (
            stats.get("motivation", 0)
            - stats.get("initial_motivation", stats.get("motivation", 0))
        )
        if motivation_change >= 8:
            reasons.append(f"drive improved by {motivation_change:.0f} points")
        if stats.get("positive_interventions", 0):
            reasons.append("responded positively to teacher support")
        standouts.append(
            {
                "name": name,
                "reason": ", ".join(reasons),
            }
        )

    follow_up_ranked = sorted(
        pupils,
        key=lambda name: (
            student_states[name].get("progress", 0),
            student_states[name].get("motivation", 0),
        ),
    )
    follow_up = []
    for name in follow_up_ranked:
        stats = student_states[name]
        needs_follow_up = (
            stats.get("progress", 0) < 45
            or stats.get("motivation", 0) < 40
            or stats.get("work_questions", 0) >= 2
        )
        if not needs_follow_up:
            continue
        reasons = []
        if stats.get("progress", 0) < 45:
            reasons.append(f"only {stats.get('progress', 0):.0f}% task progress")
        if stats.get("motivation", 0) < 40:
            reasons.append("low final drive")
        if stats.get("work_questions", 0) >= 2:
            reasons.append(
                f"asked {stats.get('work_questions', 0)} work questions"
            )
        observation = str((live_observations or {}).get(name, "")).strip()
        follow_up.append(
            {
                "name": name,
                "reason": ", ".join(reasons),
                "observation": observation[:180],
            }
        )
        if len(follow_up) >= 5:
            break

    elapsed = float(elapsed_minutes or 0)
    planned = max(1.0, float(planned_minutes or 1))
    return {
        "task": str(task or "Independent task"),
        "elapsed_minutes": elapsed,
        "planned_minutes": planned,
        "lesson_fraction": min(100, round(elapsed / planned * 100)),
        "average_progress": average_progress,
        "average_motivation": average_motivation,
        "bands": bands,
        "work_questions": total_questions,
        "interventions": total_interventions,
        "gap_themes": gap_themes,
        "standouts": standouts,
        "follow_up": follow_up,
    }


def render_learning_summary(summary):
    """Display the retained end-of-observation rehearsal debrief."""
    st.markdown("### 🧾 Rehearsal debrief")
    st.caption(
        f"Stopped after {summary['elapsed_minutes']:g} of "
        f"{summary['planned_minutes']:g} planned minutes "
        f"({summary['lesson_fraction']}%). These are generated scenario signals for "
        "rehearsal—not evidence that learning occurred and not a pupil judgement."
    )

    metric_1, metric_2, metric_3, metric_4 = st.columns(4)
    with metric_1:
        st.metric("Generated task progress", f"{summary['average_progress']}%")
    with metric_2:
        st.metric("Generated class drive", f"{summary['average_motivation']}%")
    with metric_3:
        st.metric("Work questions", summary["work_questions"])
    with metric_4:
        st.metric("Teacher interventions", summary["interventions"])

    bands = summary["bands"]
    st.markdown(
        "**Generated scenario states:** "
        f"{bands['substantial']} substantial · "
        f"{bands['secure']} secure · "
        f"{bands['developing']} developing · "
        f"{bands['limited']} limited"
    )

    gap_column, standout_column = st.columns(2)
    with gap_column:
        st.markdown("#### Predicted pressure points to rehearse")
        for gap in summary["gap_themes"]:
            st.markdown(f"- {gap}")
    with standout_column:
        st.markdown("#### Scenario standouts to notice")
        for pupil in summary["standouts"]:
            st.markdown(f"- **{pupil['name']}** — {pupil['reason']}")

    st.markdown("#### Pupils the scenario suggests checking")
    if not summary["follow_up"]:
        st.success("No pupil met the current scenario follow-up thresholds.")
    else:
        for pupil in summary["follow_up"]:
            detail = f" — last observed: {pupil['observation']}" if pupil["observation"] else ""
            st.markdown(
                f"- **{pupil['name']}** — {pupil['reason']}{detail}"
            )


def render_observation_room(df, cohort):
    teacher_name = get_teacher_display_name()
    cohort_age_context = "11 to 12" if cohort == "Year 7" else "14 to 15"
    teacher_addresses = get_teacher_address_options(teacher_name)
    address_instruction = get_teacher_address_instruction(teacher_name)
    teacher_key = re.sub(
        r"[^a-z0-9]+",
        "_",
        "|".join(teacher_addresses).casefold(),
    ).strip("_") or "teacher"
    if "seating_plans" not in st.session_state:
        st.session_state.seating_plans = {}
    plan_key, seating_plan, plan_created = ensure_suggested_plan(
        st.session_state.seating_plans,
        df,
        cohort,
    )
    observation_context = f"{plan_key}|{'|'.join(teacher_addresses).casefold()}"
    previous_context = st.session_state.get("obs_class_context")
    if previous_context and previous_context != observation_context:
        reset_keys = {
            "obs_task",
            "obs_image",
            "live_observations",
            "obs_intervene_target",
            "obs_active_students",
            "obs_task_duration",
            "obs_time_elapsed",
            "obs_engagement_log",
            "obs_global_event",
            "obs_lesson_stopped",
            "obs_learning_summary",
            "student_states",
        }
        for key in list(st.session_state.keys()):
            if key in reset_keys or str(key).startswith("obs_chat_"):
                del st.session_state[key]
    st.session_state.obs_class_context = observation_context
    df = order_dataframe_by_plan(df, seating_plan)

    col_header1, col_header2 = st.columns([3, 1])
    with col_header1:
        st.subheader("👁️ Circulate the Room: Full Class Observation")
        st.caption(
            "Generated profile-informed predictions for practising observation and "
            "intervention—not evidence of actual pupil learning."
        )
    with col_header2:
        enable_voice = st.toggle("🔊 Voice Audio", value=True, key="obs_voice_toggle")

    if plan_created:
        st.info(
            "A suggested seating plan was created from the spreadsheet relationship "
            "data. You can adjust it on the Seating Plan page."
        )
    render_seating_plan_overview(seating_plan, df, "Observe Learning")

    if not genai.configure_selected_provider():
        return

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
    if "obs_lesson_stopped" not in st.session_state: st.session_state.obs_lesson_stopped = False
    if "obs_learning_summary" not in st.session_state: st.session_state.obs_learning_summary = None
    
    if "student_states" not in st.session_state: st.session_state.student_states = {}

    if st.session_state.obs_active_students:
        active_set = set(st.session_state.obs_active_students)
        st.session_state.obs_active_students = [
            name
            for name in df["Full Name"].tolist()
            if name in active_set
        ]
        for name in st.session_state.obs_active_students:
            matching_rows = df[df["Full Name"] == name]
            if matching_rows.empty:
                continue
            defaults = build_student_observation_state(matching_rows.iloc[0])
            existing = st.session_state.student_states.setdefault(name, {})
            for key, value in defaults.items():
                existing.setdefault(key, value)

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
            st.info(f"**Generated observation:** {observation}")
        
        chat_key = f"obs_chat_{target_name}_{teacher_key}"
        if chat_key not in st.session_state: st.session_state[chat_key] = []

        col_a, col_b = st.columns([1, 3])
        with col_a:
            display_student_photo(target_name, cohort)
            st.metric("Generated drive", f"{current_mot}%")
            if st.button("🔙 Step Away (Back to Room)", width="stretch"):
                st.session_state.obs_intervene_target = None
                st.rerun()

        with col_b:
            if "latest_audio_obs" in st.session_state:
                st.audio(st.session_state["latest_audio_obs"], format="audio/wav", autoplay=True)
                del st.session_state["latest_audio_obs"]

            for msg in st.session_state[chat_key]:
                with st.chat_message(msg["role"]):
                    speaker = (
                        teacher_name
                        if msg["role"] == "user"
                        else target_name
                    )
                    st.markdown(f"**{speaker}**")
                    st.write(msg["content"])

            teacher_input = st.chat_input(f"Approach {target_name} and say...")

            if teacher_input:
                st.session_state[chat_key].append({"role": "user", "content": teacher_input})
                with st.chat_message("user"):
                    st.markdown(f"**{teacher_name}**")
                    st.write(teacher_input)

                target_row = df[df["Full Name"] == target_name].iloc[0]
                response_profile = get_ai_response_profile(target_row, cohort)
                
                transcript = "\n".join(
                    f"{teacher_name if m['role']=='user' else target_name}: "
                    f"{m['content']}"
                    for m in st.session_state[chat_key]
                )

                secret_event = st.session_state.student_states[target_name].get("current_event")
                event_context = ""
                if secret_event:
                    event_context = f"SECRET CONTEXT: You currently have your hand raised because: '{secret_event}'. When the teacher speaks to you, address this immediately.\n"
                elif st.session_state.obs_global_event:
                    event_context = f"SECRET CONTEXT: The room is chaotic because: '{st.session_state.obs_global_event}'. Address this.\n"

                system_prompt = (
                    "**[FICTIONAL SCENARIO FOR TEACHER TRAINING - ALL DATA IS MOCK/SYNTHETIC]**\n"
                    f"You are roleplaying as a UK student aged {cohort_age_context} named {target_name}.\n"
                    f"Compact pupil response profile: {response_profile}\n"
                    f"Task: '{st.session_state.obs_task}'\n"
                    f"{event_context}"
                    "Generate the most plausible next response predicted from the pupil's "
                    "age, attainment, confidence, participation, processing and current "
                    "scenario state. This is rehearsal, not observed evidence.\n"
                    f"{address_instruction}\n"
                    f"Your current internal motivation level is {current_mot}/100.\n\n"
                    f"Transcript:\n{transcript}\n\n"
                    "CRITICAL RULES:\n"
                    "1. Evaluate the teacher's last statement. Is it specific praise, helpful scaffolding, dismissive, or overly harsh?\n"
                    "2. Based on their pedagogy, determine how this affects your motivation. Create a 'motivation_delta' integer between -25 (terrible) and +35 (great).\n"
                    f"3. Respond verbally as {target_name}. Include non-verbal actions in asterisks.\n"
                    "4. Do not force useful reasoning. An age-natural 'I don't know', fragment, silence or refusal is valid when supported by the profile. Preserve a probable or possible misconception rather than making the pupil instantly correct.\n"
                    "5. Pick ONE emotion: [neutral, defensive, embarrassed, frustrated, bored, proud, eager].\n"
                    "6. Return ONLY a raw JSON object with keys: \"dialogue\", \"emotion\", and \"motivation_delta\".\n"
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
                            st.error(
                                f"⚠️ {genai.provider_name()} returned no content. "
                                "Try rewording the interaction."
                            )
                            st.stop()
                            
                        raw_text = response.text.replace("```json", "").replace("```", "")
                        ai_data = json.loads(raw_text.strip())

                        display_text = ai_data.get("dialogue", "...")
                        delta = int(ai_data.get("motivation_delta", 0))
                        
                        new_mot = min(100, max(0, current_mot + delta))
                        target_stats = st.session_state.student_states[target_name]
                        target_stats["motivation"] = new_mot
                        target_stats["interventions"] = (
                            target_stats.get("interventions", 0) + 1
                        )
                        if delta > 0:
                            target_stats["positive_interventions"] = (
                                target_stats.get("positive_interventions", 0) + 1
                            )
                        
                        target_stats["current_event"] = None
                        target_stats["current_event_kind"] = None
                        
                        if delta > 0:
                            st.success(
                                f"📈 Scenario drive increased by {delta}% "
                                f"(Now {new_mot}%)"
                            )
                        elif delta < 0:
                            st.error(
                                f"📉 Scenario drive dropped by {abs(delta)}% "
                                f"(Now {new_mot}%)"
                            )
                        else:
                            st.info(f"➖ Neutral interaction.")
                        
                    except Exception as e:
                        st.error(f"{genai.provider_name()} error: {e}")
                        st.stop()

                st.session_state[chat_key].append({"role": "assistant", "content": display_text})
                with st.chat_message("assistant"):
                    st.markdown(f"**{target_name}**")
                    st.write(display_text)

                audio_text = re.sub(r'[*\[(].*?[*\])]', '', display_text).strip()

                if enable_voice and audio_text:
                    student_voice_id = target_row.get("Voice_Name", "JBFqnCBsd6RMkjVDRZzb")
                    audio_bytes = get_elevenlabs_audio(
                        audio_text,
                        student_voice_id,
                        cohort,
                    )
                    if audio_bytes:
                        st.session_state["latest_audio_obs"] = audio_bytes
                        
                st.rerun()

    # --- 3. THE FULL ROOM VIEW ---
    else:
        st.markdown("### 1. Set the Independent Task")
        st.caption(
            "The room is calibrated to be mainly purposeful. Work-related questions "
            "are common; toilet requests and peer disruption are rare class-level events."
        )
        st.caption(
            f"Teacher speaker label: **{teacher_name}** · Pupils may address you as "
            + " or ".join(
                f"**{address}**"
                for address in teacher_addresses
            )
            + ". Change this in the sidebar."
        )
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
                st.session_state.obs_lesson_stopped = False
                st.session_state.obs_learning_summary = None
                
                if uploaded_file is not None:
                    st.session_state.obs_image = Image.open(uploaded_file)
                else:
                    st.session_state.obs_image = None
                
                st.session_state.obs_active_students = df["Full Name"].tolist()
                
                for _, row in df.iterrows():
                    name = row["Full Name"]
                    st.session_state.student_states[name] = (
                        build_student_observation_state(row)
                    )
                
                st.session_state.live_observations = {name: "Waiting for task to begin." for name in st.session_state.obs_active_students}
                st.rerun()

        with col2:
            if st.session_state.obs_active_students:
                if (
                    st.session_state.obs_time_elapsed
                    >= st.session_state.obs_task_duration
                    and st.session_state.obs_time_elapsed > 0
                ):
                    st.session_state.obs_lesson_stopped = True
                
                st.markdown("### ⚙️ Time Controls")
                advance_pct = st.slider(
                    "Advance Time (% of Total Duration):",
                    min_value=5,
                    max_value=100,
                    value=10,
                    step=5,
                    disabled=st.session_state.obs_lesson_stopped,
                )
                
                step_minutes = round((advance_pct / 100.0) * st.session_state.obs_task_duration, 1)
                time_multiplier = step_minutes / 5.0 
                
                act_col1, act_col2 = st.columns(2)
                
                with act_col1:
                    if st.session_state.obs_time_elapsed == 0:
                        if st.button(
                            f"👀 Watch Class Start (First {advance_pct}%)",
                            type="secondary",
                            width="stretch",
                            disabled=st.session_state.obs_lesson_stopped,
                        ):
                            st.session_state.obs_time_elapsed += step_minutes
                            
                            profiles = []
                            for name in st.session_state.obs_active_students:
                                stats = st.session_state.student_states[name]
                                profiles.append(
                                    f"- {name} | Readiness: {stats['motivation']}% | "
                                    f"Participation: {stats['participation']:.0f}/100 | "
                                    f"Confidence: {stats['confidence']:.0f}/100 | "
                                    f"Independence: {stats['independence']:.0f}/100 | "
                                    f"Processing speed: {stats['processing_speed']:.0f}/100"
                                )
                            
                            start_prompt = (
                                "**[FICTIONAL SCENARIO FOR TEACHER TRAINING - ALL DATA IS MOCK/SYNTHETIC]**\n"
                                f"Class age: {cohort_age_context}.\n"
                                f"Task: '{current_task}'\n"
                                f"The teacher has just said 'Go!'. Generate the most plausible profile-informed prediction for the first {step_minutes} minutes. This is rehearsal, not observed evidence.\n"
                                f"Current Class Profiles:\n{chr(10).join(profiles)}\n\n"
                                "CRITICAL RULES:\n"
                                "1. Model a purposeful but varied classroom. Most pupils should begin the work.\n"
                                "   - Readiness >70: usually engages within 0:00 to 0:45.\n"
                                "   - Readiness 50-70: usually engages within 0:30 to 2:30.\n"
                                f"   - Readiness <50: may need settling or reassurance, but should still make an attempt within {step_minutes} minutes unless the data strongly supports non-start.\n"
                                "2. Across the class, at least 80% should start during this window. Return 'Failed' only for a small, data-supported minority.\n"
                                "3. Describe observable work-start behaviour: reading instructions, writing, organising equipment, checking an example or raising a work-related question. Do not invent toilet requests or peer disruption.\n"
                                "4. Return ONLY a JSON dictionary where keys are names and values are dicts containing 'time' and 'desc'.\n"
                            )
                            
                            with st.spinner("Watching the room settle..."):
                                try:
                                    model = genai.GenerativeModel(REACTION_MODEL)
                                    contents = [start_prompt]
                                    if st.session_state.obs_image is not None: contents.append(st.session_state.obs_image)
                                        
                                    response = model.generate_content(contents, generation_config={"response_mime_type": "application/json"})
                                    
                                    if not response.parts:
                                        st.error(
                                            f"⚠️ {genai.provider_name()} returned no "
                                            "room-generation content."
                                        )
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
                        if st.button(
                            f"⏱️ Advance Time ({advance_pct}%) & Scan Room",
                            width="stretch",
                            disabled=st.session_state.obs_lesson_stopped,
                        ):
                            st.session_state.obs_time_elapsed += step_minutes
                            if st.session_state.obs_time_elapsed > st.session_state.obs_task_duration:
                                st.session_state.obs_time_elapsed = st.session_state.obs_task_duration
                            
                            st.session_state.obs_global_event = None
                            global_prompt_injection = ""
                            
                            dice_roll = random.randint(1, 100)
                            if dice_roll <= 1:
                                st.session_state.obs_global_event = "It has started snowing heavily outside the window."
                                global_prompt_injection = f"URGENT GLOBAL EVENT: {st.session_state.obs_global_event} Everyone is distracted."
                                st.toast("❄️ It started snowing!", icon="❄️")
                            elif dice_roll <= 2:
                                st.session_state.obs_global_event = "A large wasp has flown into the classroom."
                                global_prompt_injection = f"URGENT GLOBAL EVENT: {st.session_state.obs_global_event} Students are reacting or panicking."
                                st.toast("🐝 A wasp flew in!", icon="🐝")

                            for name in st.session_state.obs_active_students:
                                stats = st.session_state.student_states[name]
                                stats["current_event"] = None
                                stats["current_event_kind"] = None
                                
                                if st.session_state.obs_global_event:
                                    stats["motivation"] = max(0, stats["motivation"] - random.randint(20, 40))
                                else:
                                    decay_amount = int(stats["decay_rate"] * time_multiplier)
                                    stats["motivation"] = max(0, stats["motivation"] - decay_amount)
                                
                                if stats["motivation"] > 30:
                                    prog_amount = int(
                                        random.randint(12, 28)
                                        * time_multiplier
                                        * stats.get("work_rate", 1.0)
                                    )
                                    stats["progress"] = min(100, stats["progress"] + prog_amount)

                            if not st.session_state.obs_global_event:
                                class_events = assign_classroom_events(
                                    st.session_state.obs_active_students,
                                    df,
                                    st.session_state.student_states,
                                    st.session_state.obs_time_elapsed,
                                )
                                for name, event in class_events.items():
                                    stats = st.session_state.student_states[name]
                                    stats["current_event"] = event["context"]
                                    stats["current_event_kind"] = event["kind"]
                                    if event["kind"] == "work_question":
                                        stats["work_questions"] = (
                                            stats.get("work_questions", 0) + 1
                                        )

                            profiles = []
                            for name in st.session_state.obs_active_students:
                                mot = st.session_state.student_states[name]["motivation"]
                                prog = st.session_state.student_states[name]["progress"]
                                has_event = st.session_state.student_states[name].get("current_event") is not None
                                event_kind = st.session_state.student_states[name].get("current_event_kind")
                                evt_string = (
                                    f" | STATUS: Has their hand up waiting for the teacher "
                                    f"(internal event type: {event_kind})."
                                    if has_event
                                    else ""
                                )
                                profiles.append(f"- {name} | Motivation: {mot}% | Progress: {prog}%{evt_string}")
                            
                            obs_prompt = (
                                "**[FICTIONAL SCENARIO FOR TEACHER TRAINING - ALL DATA IS MOCK/SYNTHETIC]**\n"
                                f"Class age: {cohort_age_context}.\n"
                                f"Task: '{current_task}'\n"
                                f"{global_prompt_injection}\n"
                                f"Generate a 1-sentence predicted physical observation of each student based on their numbers and STATUS. These are plausible rehearsal predictions, not observed facts.\n"
                                f"{chr(10).join(profiles)}\n\n"
                                "RULES:\n"
                                "1. If a student's STATUS says they have their hand up, describe them physically raising their hand. Do not announce the hidden reason.\n"
                                "2. Otherwise, show purposeful work by default: reading, writing, calculating, checking, editing or using the resource. Motivation >65 is focused; 45-65 is mainly working with an occasional pause; 30-45 is working intermittently; only below 30 is clearly off-task.\n"
                                "3. Do not invent toilet requests, conversations or peer distraction unless an explicit STATUS or global event requires it. Avoid making neighbouring pupils distract one another by default.\n"
                                "4. Vary the observations and show progress through the actual task rather than repeatedly describing attention alone.\n"
                                "5. Return ONLY a raw JSON dict with names as keys and observations as values."
                            )
                            
                            with st.spinner(f"Scanning {len(st.session_state.obs_active_students)} students..."):
                                try:
                                    model = genai.GenerativeModel(REACTION_MODEL)
                                    contents = [obs_prompt]
                                    if st.session_state.obs_image is not None: contents.append(st.session_state.obs_image)
                                        
                                    response = model.generate_content(contents, generation_config={"response_mime_type": "application/json"})
                                    
                                    if not response.parts:
                                        st.error(
                                            f"⚠️ {genai.provider_name()} returned no "
                                            "scan content."
                                        )
                                        st.stop()
                                        
                                    raw_text = response.text.replace("```json", "").replace("```", "")
                                    st.session_state.live_observations = json.loads(raw_text.strip())
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Failed scan: {e}")

                with act_col2:
                    if not st.session_state.obs_lesson_stopped:
                        if st.button(
                            "⏹️ Stop class and summarise",
                            type="primary",
                            width="stretch",
                        ):
                            st.session_state.obs_lesson_stopped = True
                            st.session_state.obs_learning_summary = None
                            st.rerun()
                    else:
                        st.success("Class stopped. The rehearsal debrief is available below.")
                        if (
                            st.session_state.obs_time_elapsed
                            < st.session_state.obs_task_duration
                            and st.button(
                                "▶️ Resume observation",
                                width="stretch",
                            )
                        ):
                            st.session_state.obs_lesson_stopped = False
                            st.session_state.obs_learning_summary = None
                            st.rerun()

                    if st.button("🔄 Restart Activity (Reset Clock & Drive)", width="stretch"):
                        st.session_state.obs_time_elapsed = 0
                        st.session_state.obs_engagement_log = None
                        st.session_state.obs_global_event = None
                        st.session_state.obs_lesson_stopped = False
                        st.session_state.obs_learning_summary = None
                        
                        for name in st.session_state.obs_active_students:
                            row = df[df["Full Name"] == name].iloc[0]
                            st.session_state.student_states[name] = (
                                build_student_observation_state(row)
                            )
                        
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
            with dash_col1: st.metric("Generated Class Drive", f"{avg_mot}%")
            with dash_col2: st.metric("Generated Task Progress", f"{avg_prog}%")
            with dash_col3: st.metric("Students Monitored", len(st.session_state.obs_active_students))

            if st.session_state.obs_lesson_stopped:
                if st.session_state.obs_learning_summary is None:
                    st.session_state.obs_learning_summary = build_learning_summary(
                        st.session_state.obs_active_students,
                        st.session_state.student_states,
                        st.session_state.obs_engagement_log,
                        st.session_state.live_observations,
                        st.session_state.obs_time_elapsed,
                        st.session_state.obs_task_duration,
                        st.session_state.obs_task,
                    )
                if st.session_state.obs_learning_summary:
                    st.markdown("---")
                    render_learning_summary(
                        st.session_state.obs_learning_summary
                    )
            
            st.markdown("### 📢 Broadcast to Class")
            st.caption("Address the entire room at once. Use this to reset focus, give a time warning, or clarify the task.")
            
            class_announcement = st.chat_input(
                "Speak to the entire class...",
                disabled=st.session_state.obs_lesson_stopped,
            )
            if class_announcement:
                with st.spinner("The class is processing your announcement..."):
                    profiles_str = "\n".join([f"- {name} (Mot: {st.session_state.student_states[name]['motivation']}%)" for name in st.session_state.obs_active_students])
                    
                    broadcast_prompt = (
                        "**[FICTIONAL SCENARIO FOR TEACHER TRAINING - ALL DATA IS MOCK/SYNTHETIC]**\n"
                        "Generate profile-informed predicted reactions for rehearsal, "
                        "not observed facts about these pupils.\n"
                        f"{address_instruction}\n"
                        f"{teacher_name} just addressed the entire class aloud: "
                        f"'{class_announcement}'\n\n"
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
                            st.error(
                                f"⚠️ {genai.provider_name()} returned no class "
                                "reaction content."
                            )
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
                        st.success(
                            f"📣 {teacher_name} said: '{class_announcement}' — "
                            "The room has reacted."
                        )
                        
                    except Exception as e:
                        st.error(f"Failed to process class announcement: {e}")

            st.markdown("---")
            
            # SECTION C: The Student Grid
            num_cols = plan_display_columns(seating_plan)
            for i in range(0, len(st.session_state.obs_active_students), num_cols):
                cols = st.columns(num_cols)
                for idx, student_name in enumerate(st.session_state.obs_active_students[i : i + num_cols]):
                    with cols[idx]:
                        with st.container(border=True):
                            display_student_photo(student_name, cohort)
                            st.markdown(f"**{student_name}**")
                            
                            stats = st.session_state.student_states[student_name]
                            
                            mot_color = "🟢" if stats["motivation"] > 65 else "🟡" if stats["motivation"] > 35 else "🔴"
                            st.caption(
                                f"{mot_color} **Generated drive:** "
                                f"{stats['motivation']}% | 📋 **Scenario progress:** "
                                f"{stats['progress']}%"
                            )
                            
                            if stats.get("current_event"):
                                st.warning(f"🙋 **Hand Raised**")
                            
                            obs_text = st.session_state.live_observations.get(student_name, "Waiting for scan...")
                            st.info(f"*{obs_text}*")
                            
                            if st.button(
                                "🗣️ Intervene",
                                key=f"int_{student_name}",
                                width="stretch",
                                disabled=st.session_state.obs_lesson_stopped,
                            ):
                                st.session_state.obs_intervene_target = student_name
                                st.rerun()
