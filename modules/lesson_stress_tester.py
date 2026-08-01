import streamlit as st
import json
from PIL import Image
import pypdf
import docx
from config import ANALYSIS_MODEL
from modules import ai_client as genai
from modules.data_utils import get_ai_response_profile

def get_flexible_text(row, possible_names):
    """Helper to safely extract data from the row."""
    row_keys = {str(k).strip().lower(): k for k in row.keys()}
    for name in possible_names:
        clean_name = name.lower().strip()
        if clean_name in row_keys:
            val = str(row[row_keys[clean_name]]).strip()
            if val and val.upper() not in ["NAN", "N/A", "NONE", "NULL", ""]:
                if val.endswith(".0"): val = val[:-2]
                return val
    return "None recorded"


def build_lesson_prediction_prompt(
    lesson_content,
    profiles_text,
    pupil_count,
    cohort,
    subject,
    age_context,
    key_stage,
):
    """Build an evidence-grounded lesson-risk and response-prediction prompt."""
    return f"""
    You are an expert UK ITT curriculum mentor and assessment designer. Analyse a
    planned lesson from outside the learner: do not claim that an LLM simulation proves
    what pupils know or whether the lesson will work.

    Subject: {subject}
    Cohort: {cohort} ({age_context})
    Curriculum stage: {key_stage}

    LESSON PLAN:
    {lesson_content or "The lesson plan is supplied in the attached image."}

    COMPACT, PRIVACY-MINIMISED PUPIL RESPONSE PROFILES ({pupil_count} pupils):
    {profiles_text}

    EPISTEMIC RULES:
    - Every pupil response is a profile-informed prediction for teacher rehearsal, not
      observed evidence and not a claim about what that pupil will definitely say.
    - "Probable" means strongly supported by the lesson demands and supplied profile.
      "Possible" means a credible alternative worth rehearsing.
    - Predict the most plausible age-appropriate response form: secure, partial,
      misconception, slip, uncertain or no attempt.
    - Include probable and possible subject-specific misconceptions where justified.
      A realistic response may be "I don't know", "not sure", a fragment, silence or a
      refusal. Never add hidden correct reasoning to make a non-attempt informative.
    - Do not make pupils unusually articulate, compliant or uniformly successful.
    - Do not infer a response from a protected characteristic or SEND label alone.
    - If evidence is missing from the lesson, say "Not visible"; do not invent it.

    ANALYSIS REQUIREMENTS:
    1. Check curriculum pitch and prerequisite knowledge for {key_stage} {subject}.
    2. Identify explanation jumps, ambiguous wording, reading/vocabulary demand,
       working-memory load, weak modelling and transitions between guided and
       independent practice.
    3. Identify where probable and possible misconceptions could be elicited.
    4. Check whether planned questions reveal partial understanding, misconceptions
       and non-attempts before the lesson moves on.
    5. Use profiles as planning evidence for access hypotheses while preserving high
       expectations and avoiding low-ceiling tasks.
    6. For every risk, state the source evidence, likelihood, practical repair and a
       live check that could confirm or disconfirm the prediction with real pupils.

    ANTI-PATTERN GUARDRAILS:
    - Do not use VAK learning styles, left/right-brain claims or the Learning Pyramid.
    - Do not suggest "mild, spicy, hot" tasks or fixed low-ability worksheets.
    - Do not expose private home-life or safeguarding information.

    Return ONLY valid JSON:
    {{
      "metrics": {{
        "high_priority_risks": <non-negative integer>,
        "possible_risks": <non-negative integer>,
        "prerequisites_not_visible": <non-negative integer>,
        "assessment_gaps": <non-negative integer>,
        "overall_risk": "<Low, Moderate or High>",
        "confidence": "<Low, Medium or High>"
      }},
      "overview": "<2-3 sentences separating evidence from prediction>",
      "audit": {{
        "curriculum_pitch": "<evidence-grounded judgement>",
        "prerequisites": "<secured, assumed or not visible>",
        "explanation_and_modelling": "<analysis>",
        "task_and_language_demand": "<analysis>",
        "checking_for_understanding": "<analysis>"
      }},
      "risk_register": [
        {{
          "location": "<lesson phase/task/question>",
          "risk_type": "<prerequisite, misconception, ambiguity, cognitive load, access or assessment>",
          "likelihood": "<Probable or Possible>",
          "source_evidence": "<specific feature in the supplied lesson>",
          "prediction": "<what may break and why>",
          "suggested_change": "<precise repair>",
          "live_check": "<what to check with real pupils>"
        }}
      ],
      "profile_predictions": [
        {{
          "name": "<exact pupil name from the supplied profiles>",
          "profile_basis": "<non-sensitive qualities relevant to this lesson>",
          "most_likely_response": "<age-authentic predicted answer form; may include IDK>",
          "probable_misconception": "<specific misconception or 'None strongly indicated'>",
          "possible_misconception": "<credible alternative misconception>",
          "confidence": "<Low, Medium or High>",
          "planning_response": "<high-expectation scaffold, probe or extension>",
          "verify_live": "<question or observable evidence needed in the real lesson>"
        }}
      ],
      "priority_actions": [
        {{
          "action": "<specific lesson revision>",
          "reason": "<why it improves access or diagnosis>",
          "evidence_to_collect": "<real-pupil evidence to collect>"
        }}
      ],
      "limitations": "<one sentence stating that predictions require real-pupil validation>"
    }}

    Select exactly 4 distinct pupils for profile_predictions, representing contrasting
    attainment, confidence, participation, processing and access patterns rather than
    simply selecting pupils with SEND.
    """


def normalise_lesson_prediction_result(result, allowed_names):
    """Constrain named predictions and list-shaped model output."""
    clean_result = result if isinstance(result, dict) else {}
    for dict_key in ("metrics", "audit"):
        if not isinstance(clean_result.get(dict_key), dict):
            clean_result[dict_key] = {}
    for list_key in ("risk_register", "profile_predictions", "priority_actions"):
        if not isinstance(clean_result.get(list_key), list):
            clean_result[list_key] = []
        clean_result[list_key] = [
            item
            for item in clean_result[list_key]
            if isinstance(item, dict)
        ]

    allowed = {str(name).strip() for name in allowed_names}
    clean_result["profile_predictions"] = [
        prediction
        for prediction in clean_result["profile_predictions"]
        if str(prediction.get("name", "")).strip() in allowed
    ][:4]
    return clean_result


def render_stress_tester(df, cohort, subject="General"):
    st.subheader(f"🌩️ Lesson Plan Stress-Tester: {cohort} {subject}")
    
    if not genai.configure_selected_provider():
        return

    # --- THE SIDEBAR LEGEND (Framework Clarity) ---
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🧬 Prediction framework")
    st.sidebar.caption(
        "This audit predicts plausible pressure points for rehearsal; it does not "
        "simulate proof that pupils have learned. It draws on:\n\n"
        "* **UK National Curriculum:** Age-appropriate pitching for KS3/KS4.\n"
        "* **Rosenshine's Principles:** Small steps modeling, guided practice, active checks.\n"
        "* **Cognitive Load Theory (Sweller):** Working memory optimization & schema integration.\n"
        "* **Tom Sherrington's 'First Principles':** Explicit teaching mechanics.\n"
        "* **Adaptive Teaching:** Differentiation by scaffolding rather than task-splitting."
    )
    
    st.sidebar.markdown("### 🚫 Anti-Patterns Enforced")
    st.sidebar.caption("The AI is strictly constrained against deploying educational neuromyths (e.g., VAK Learning Styles) or superficial differentiation fads (e.g., 'Mild, Spicy, Hot' tasks).")

    # --- 1. THE INPUT AREA ---
    st.markdown("### 1. Provide the Lesson Plan")
    uploaded_file = st.file_uploader("Upload your Lesson Plan document (PDF, Word, TXT, or Image):", type=['pdf', 'docx', 'txt', 'png', 'jpg', 'jpeg'])
    
    extracted_text = ""
    image_parts = []

    if uploaded_file is not None:
        file_ext = uploaded_file.name.split(".")[-1].lower()
        
        if file_ext in ["png", "jpg", "jpeg"]:
            st.image(uploaded_file, caption="Lesson Plan Resource Scan", width="stretch")
            image_parts.append(Image.open(uploaded_file))
            
        elif file_ext == "pdf":
            try:
                pdf_reader = pypdf.PdfReader(uploaded_file)
                for page in pdf_reader.pages:
                    extracted_text += page.extract_text() + "\n"
                st.success(f"📄 Extracted data from PDF.")
            except Exception as e:
                st.error(f"Error reading PDF: {e}")
                
        elif file_ext == "docx":
            try:
                doc = docx.Document(uploaded_file)
                for para in doc.paragraphs:
                    extracted_text += para.text + "\n"
                st.success("📄 Extracted data from Word Document.")
            except Exception as e:
                st.error(f"Error reading Word document: {e}")
                
        elif file_ext == "txt":
            extracted_text = uploaded_file.getvalue().decode("utf-8")
            st.success("📄 Extracted data from text file.")

    st.markdown("---")
    
    if not uploaded_file:
        st.info("👆 Please upload a lesson plan document to begin the prediction audit.")
        return

    final_lesson_content = extracted_text.strip()

    # --- 2. EXECUTE THE STRESS TEST ---
    if st.button("🚀 Analyse likely pressure points", type="primary", width="stretch"):
        with st.spinner(
            "Analysing lesson evidence and generating profile-informed predictions..."
        ):
            
            # Contextualize Age and Curriculum Stage
            if cohort == "Year 7":
                age_context = "11 to 12 years old"
                key_stage = "Key Stage 3 (KS3)"
            else:
                age_context = "14 to 15 years old"
                key_stage = "Key Stage 4 (KS4 / GCSE)"

            profiles = []
            for _, row in df.iterrows():
                name = row.get("Full Name", "Unknown")
                response_profile = get_ai_response_profile(
                    row,
                    cohort,
                    subject,
                    max_chars=1000,
                )
                profiles.append(f"- {name}: {response_profile}")
            profiles_text = "\n".join(profiles)

            system_prompt = build_lesson_prediction_prompt(
                final_lesson_content,
                profiles_text,
                len(df),
                cohort,
                subject,
                age_context,
                key_stage,
            )

            model = genai.GenerativeModel(ANALYSIS_MODEL)
            contents = [system_prompt]
            if image_parts:
                contents.extend(image_parts)

            try:
                response = model.generate_content(contents, generation_config={"response_mime_type": "application/json"})
                
                # COPY-PASTE SAFE JSON EXTRACTION
                raw_text = response.text
                raw_text = raw_text.replace("`" * 3 + "json", "")
                raw_text = raw_text.replace("`" * 3, "")
                result = json.loads(raw_text.strip())
                result = normalise_lesson_prediction_result(
                    result,
                    df["Full Name"].astype(str).tolist(),
                )
                
                # --- 3. RENDER THE DASHBOARD ---
                st.success("✅ Evidence-grounded prediction audit compiled")
                st.caption(
                    "These are profile-informed planning predictions, not measurements "
                    "of learning or guarantees about individual pupils."
                )
                
                # Zone 1: Metrics
                st.markdown("### 📊 Planning risk indicators")
                metrics = result.get("metrics", {})
                
                metric_columns = st.columns(6)
                metric_columns[0].metric(
                    "Overall risk",
                    metrics.get("overall_risk", "Review"),
                )
                metric_columns[1].metric(
                    "Confidence",
                    metrics.get("confidence", "Medium"),
                )
                metric_columns[2].metric(
                    "High-priority risks",
                    metrics.get("high_priority_risks", 0),
                )
                metric_columns[3].metric(
                    "Possible risks",
                    metrics.get("possible_risks", 0),
                )
                metric_columns[4].metric(
                    "Prerequisites unclear",
                    metrics.get("prerequisites_not_visible", 0),
                )
                metric_columns[5].metric(
                    "Assessment gaps",
                    metrics.get("assessment_gaps", 0),
                )

                st.info(result.get("overview", "No overview was returned."))
                
                st.divider()
                
                # Zone 2: Pedagogy Critique
                st.markdown("### 🧠 Lesson evidence audit")
                audit = result.get("audit", {})
                
                c1, c2 = st.columns(2)
                with c1:
                    st.info(
                        f"**National Curriculum & Pitch ({key_stage})**\n\n"
                        f"{audit.get('curriculum_pitch', 'Not visible')}"
                    )
                    st.success(
                        "**Prerequisites**\n\n"
                        f"{audit.get('prerequisites', 'Not visible')}"
                    )
                    st.warning(
                        "**Explanation and modelling**\n\n"
                        f"{audit.get('explanation_and_modelling', 'Not visible')}"
                    )
                with c2:
                    st.warning(
                        "**Task and language demand**\n\n"
                        f"{audit.get('task_and_language_demand', 'Not visible')}"
                    )
                    st.error(
                        "**Checking for understanding**\n\n"
                        f"{audit.get('checking_for_understanding', 'Not visible')}"
                    )

                st.markdown("### ⚠️ Evidence-grounded risk register")
                risks = result.get("risk_register", [])
                if not risks:
                    st.caption("No specific risk was returned.")
                for index, risk in enumerate(risks, start=1):
                    with st.expander(
                        f"{index}. {risk.get('likelihood', 'Possible')} · "
                        f"{risk.get('location', 'Lesson')} — "
                        f"{risk.get('risk_type', 'Risk')}",
                        expanded=index <= 2,
                    ):
                        st.write(risk.get("prediction", ""))
                        st.caption(
                            f"Source evidence: {risk.get('source_evidence', 'Not visible')}"
                        )
                        st.success(
                            f"Suggested change: {risk.get('suggested_change', '')}"
                        )
                        st.info(
                            f"Check with real pupils: {risk.get('live_check', '')}"
                        )

                st.divider()
                
                # Zone 3: Profile-informed predictions
                st.markdown("### 🔬 Profile-informed response predictions")
                st.caption(
                    "Best estimates for rehearsal. They include probable and possible "
                    "misconceptions and may predict a partial answer or 'I don't know'."
                )
                predictions = result.get("profile_predictions", [])
                
                cols = st.columns(2)
                for idx, student in enumerate(predictions[:4]):
                    col = cols[idx % 2]
                    with col:
                        with st.expander(
                            f"👤 {student.get('name', 'Pupil')} — "
                            f"{student.get('confidence', 'Medium')} confidence",
                            expanded=True,
                        ):
                            st.caption(
                                f"Profile basis: {student.get('profile_basis', 'Not stated')}"
                            )
                            st.write(
                                "**Most likely response:** "
                                f"{student.get('most_likely_response', 'Not predicted')}"
                            )
                            st.warning(
                                "**Probable misconception:** "
                                f"{student.get('probable_misconception', 'None strongly indicated')}"
                            )
                            st.info(
                                "**Possible misconception:** "
                                f"{student.get('possible_misconception', 'Not identified')}"
                            )
                            st.success(
                                "**Planning response:** "
                                f"{student.get('planning_response', 'Not identified')}"
                            )
                            st.caption(
                                "Verify live: "
                                f"{student.get('verify_live', 'Collect real-pupil evidence')}"
                            )
                            
                st.divider()
                
                # Zone 4: Priority revisions and validation
                st.markdown("### 🛠️ Priority revisions and evidence to collect")
                actions = result.get("priority_actions", [])
                for index, action in enumerate(actions, start=1):
                    st.markdown(
                        f"**{index}. {action.get('action', 'Review lesson')}**  \n"
                        f"{action.get('reason', '')}  \n"
                        f"*Collect: {action.get('evidence_to_collect', '')}*"
                    )
                st.warning(
                    result.get(
                        "limitations",
                        "Validate every prediction using evidence from real pupils.",
                    )
                )

            except Exception as e:
                st.error(f"Failed to compile the dashboard structure. Error: {e}")
