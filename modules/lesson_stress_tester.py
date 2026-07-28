import streamlit as st
import json
import time
from PIL import Image
import pypdf
import docx
from config import ANALYSIS_MODEL
from modules.app_secrets import get_secret
from modules import gemini_client as genai
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

def render_stress_tester(df, cohort, subject="General"):
    st.subheader(f"🌩️ Lesson Plan Stress-Tester: {cohort} {subject}")
    
    api_key = get_secret("GEMINI_API_KEY")
    if not api_key:
        st.error("⚠️ Gemini API Key missing. Please add it to your secrets.toml file.")
        return
    genai.configure(api_key=api_key)

    # --- THE SIDEBAR LEGEND (Framework Clarity) ---
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🧬 Simulation Frameworks")
    st.sidebar.caption(
        "This stress-test evaluates your lesson against standard UK ITT Core Content Framework metrics:\n\n"
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
        st.info("👆 Please upload a lesson plan document to begin the simulation.")
        return

    final_lesson_content = extracted_text.strip()

    # --- 2. EXECUTE THE STRESS TEST ---
    if st.button("🚀 Stress-Test Lesson", type="primary", width="stretch"):
        with st.spinner(f"Simulating the lesson against student profiles and the National Curriculum..."):
            
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

            system_prompt = f"""
            You are an elite UK Higher Education Initial Teacher Training (ITT) tutor and curriculum mentor.
            You are conducting a lesson simulation audit for a trainee's lesson plan.
            Subject: {subject}. Cohort: {cohort} (Age range: {age_context}). Educational Stage: {key_stage}.
            
            Evaluate this lesson plan against the compact, privacy-minimised profiles of these {len(df)} students:
            {profiles_text}
            
            TRAINEE'S LESSON PLAN INPUT:
            {final_lesson_content}
            
            ASSESSMENT MODEL OBJECTIVES:
            1. UK National Curriculum Alignment: Cross-reference the content pitch against the UK National Curriculum for {key_stage} {subject}. Flag if it is too elementary, developmentally inappropriate, or strays into A-Level complexity.
            2. Rosenshine's Principles of Instruction: Verify if complex tasks are broken down into small, digestible chunks with active modeling.
            3. Cognitive Load Theory (Sweller): Identify hidden memory bottle-necks, lack of procedural automaticity, or layout/presentation overload.
            4. Tom Sherrington's 'First Principles' of Teaching: Audit the transition formatting between instructional teaching, guided practice, and independent application.
            5. Adaptive Teaching & Inclusion: Balance academic attainment (KS2 scores/target grades) with their SEN needs and personal backgrounds. Do not over-fixate on hobbies; prioritize academic scaffolding.

            STRICT ANTI-PATTERN GUARDRAILS (CRITICAL):
            Under NO circumstances may your evaluation or actionable tweaks rely on debunked educational neuromyths or superficial differentiation fads. 
            - DO NOT mention or validate VAK Learning Styles (Visual, Auditory, Kinesthetic).
            - DO NOT suggest "kinesthetic" activities as an intervention for SEN or engagement.
            - DO NOT reference left-brain/right-brain dominance.
            - DO NOT reference the Learning Pyramid / Dale's Cone of Experience.
            - DO NOT use or recommend "mild, spicy, hot" (or any similar tiered) challenge systems for differentiation. Differentiation should be achieved through scaffolding UP to high expectations, not by capping task difficulty and encouraging self-limiting behavior.
            - Base all engagement strategies on motivation through success, schema building, and checking for understanding.

            TECHNICAL COMPLIANCE RULE: You must return ONLY a clean JSON object using this exact structure:
            {{
              "metrics": {{
                "predicted_mastery_count": <int>,
                "high_risk_overload_count": <int>,
                "pacing_status_label": "<Strictly 1 to 2 words ONLY. e.g., 'Optimal', 'Too Fast', 'At Risk', 'Uneven'>",
                "pacing_detailed_desc": "<1 sentence detailing the pacing and transition flow behavior>"
              }},
              "critique": {{
                "curriculum_pitch": "<1-2 sentences verifying if the pitch matches UK National Curriculum expectations for {key_stage} ({age_context})>",
                "modeling": "<1-2 sentences critiquing modeling via Rosenshine/Sherrington models>",
                "guided_practice": "<1-2 sentences evaluating the fading of scaffolding>",
                "checking_for_understanding": "<1-2 sentences auditing the AfL tracking mechanisms>"
              }},
              "focus_group": [
                {{
                  "name": "<Exact student name>",
                  "profile_type": "<e.g., SEN Support, High Attainer, Disengaged>",
                  "experience": "<1-2 sentences detailing how they will cope, balancing their academic attainment with their background context>"
                }}
              ],
              "actionable_tweaks": [
                "<Actionable pedagogical change 1>",
                "<Actionable pedagogical change 2>",
                "<Actionable pedagogical change 3>"
              ]
            }}
            * Ensure the focus_group contains exactly 4 distinct students selected out of the class list.
            """

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
                
                # --- 3. RENDER THE DASHBOARD ---
                st.success("✅ Simulation Matrix Compiled!")
                
                # Zone 1: Metrics
                st.markdown("### 📊 Class Survival Metrics")
                metrics = result.get("metrics", {})
                
                m1, m2, m3 = st.columns(3)
                m1.metric("Predicted Mastery", f"{metrics.get('predicted_mastery_count', 0)} / {len(df)}")
                m2.metric("Working Memory Overload", f"{metrics.get('high_risk_overload_count', 0)} Students", delta="Scaffolding Required", delta_color="inverse")
                m3.metric("Pacing Status", metrics.get('pacing_status_label', 'Review Flow'))
                
                if "pacing_detailed_desc" in metrics:
                    st.markdown(f"⏱️ **Pacing Analysis:** *{metrics.get('pacing_detailed_desc')}*")
                
                st.divider()
                
                # Zone 2: Pedagogy Critique
                st.markdown("### 🧠 'First Principles' & Curriculum Critique")
                critique = result.get("critique", {})
                
                c1, c2 = st.columns(2)
                with c1:
                    st.info(f"**National Curriculum & Pitch ({key_stage})**\n\n{critique.get('curriculum_pitch', 'N/A')}")
                    st.success(f"**Modeling & Schema (Rosenshine)**\n\n{critique.get('modeling', 'N/A')}")
                with c2:
                    st.warning(f"**Guided Practice Mechanics**\n\n{critique.get('guided_practice', 'N/A')}")
                    st.error(f"**AfL Checkpoints (Sherrington)**\n\n{critique.get('checking_for_understanding', 'N/A')}")
                
                st.divider()
                
                # Zone 3: Focus Group
                st.markdown("### 🔬 Student Focus Group (Academic & Contextual)")
                st.caption("How 4 specific students will likely experience this lesson based on their full profiles:")
                focus_group = result.get("focus_group", [])
                
                cols = st.columns(2)
                for idx, student in enumerate(focus_group[:4]):
                    col = cols[idx % 2]
                    with col:
                        with st.expander(f"👤 {student.get('name', 'Student')} — {student.get('profile_type', 'Profile')}", expanded=True):
                            st.write(student.get("experience", "No data compiled."))
                            
                st.divider()
                
                # Zone 4: Actionable Tweaks
                st.markdown("### 🛠️ The 'S-Plan' Recommended Interventions")
                tweaks = result.get("actionable_tweaks", [])
                for i, tweak in enumerate(tweaks):
                    st.markdown(f"**{i+1}.** {tweak}")

            except Exception as e:
                st.error(f"Failed to compile the dashboard structure. Error: {e}")
