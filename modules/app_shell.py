"""Visual shell, navigation, and home page for the teaching studio."""

from collections.abc import Mapping

import pandas as pd
import streamlit as st

from config import APP_NAME, APP_SHORT_NAME, APP_TAGLINE, APP_VERSION


NAV_ITEMS = [
    "Home",
    "Student Search",
    "Year 7",
    "Year 10",
    "Analytics",
    "Seating Plan",
    "Simulator",
    "Academic AfL",
    "Lesson Stress-Tester",
    "Sequence Evaluator",
    "Observe Learning",
]

NAV_LABELS = {
    "Home": "⌂  Home",
    "Student Search": "⌕  Student search",
    "Year 7": "◫  Year 7 passports",
    "Year 10": "◫  Year 10 passports",
    "Analytics": "↗  Cohort analytics",
    "Seating Plan": "▦  Seating plan",
    "Simulator": "◉  Student roleplay",
    "Academic AfL": "✓  Academic AfL",
    "Lesson Stress-Tester": "⚡  Lesson stress-test",
    "Sequence Evaluator": "⇥  Sequence evaluator",
    "Observe Learning": "◎  Observe learning",
}


def apply_app_styles() -> None:
    """Apply a restrained, accessible visual system across existing pages."""
    st.markdown(
        """
        <style>
            :root {
                --studio-ink: #152033;
                --studio-muted: #5f6b7a;
                --studio-blue: #3157d5;
                --studio-teal: #0f766e;
                --studio-line: #dce3ee;
                --studio-panel: #ffffff;
            }
            .stApp {
                background:
                    radial-gradient(circle at 84% 6%, rgba(49, 87, 213, .08), transparent 24rem),
                    #f7f8fc;
            }
            [data-testid="stSidebar"] {
                background: linear-gradient(180deg, #101c34 0%, #182843 100%);
                color: #f4f7ff;
            }
            [data-testid="stSidebar"] p,
            [data-testid="stSidebar"] label,
            [data-testid="stSidebar"] h1,
            [data-testid="stSidebar"] h2,
            [data-testid="stSidebar"] h3 {
                color: #f4f7ff;
            }
            [data-testid="stSidebar"] [data-baseweb="select"] *,
            [data-testid="stSidebar"] input {
                color: var(--studio-ink);
            }
            [data-testid="stSidebar"] [data-baseweb="radio"] > div {
                gap: .2rem;
            }
            [data-testid="stSidebar"] hr {
                border-color: rgba(255,255,255,.16);
            }
            [data-testid="stSidebar"] .stAlert * {
                color: var(--studio-ink);
            }
            .block-container {
                max-width: 1320px;
                padding-top: 2rem;
                padding-bottom: 4rem;
            }
            h1, h2, h3 {
                color: var(--studio-ink);
                letter-spacing: -.025em;
            }
            .studio-brand {
                padding: .3rem 0 1rem;
            }
            .studio-brand__eyebrow {
                color: #94aefc;
                font-size: .72rem;
                font-weight: 750;
                letter-spacing: .14em;
                text-transform: uppercase;
            }
            .studio-brand__name {
                color: white;
                font-size: 1.35rem;
                font-weight: 760;
                line-height: 1.15;
                margin-top: .35rem;
            }
            .studio-brand__tagline {
                color: #c9d5ef;
                font-size: .84rem;
                line-height: 1.45;
                margin-top: .5rem;
            }
            .studio-hero {
                background: linear-gradient(135deg, #16233e 0%, #2547b8 65%, #0f766e 120%);
                border-radius: 1.35rem;
                box-shadow: 0 18px 50px rgba(20, 34, 65, .16);
                color: white;
                margin-bottom: 1.3rem;
                overflow: hidden;
                padding: clamp(1.7rem, 4vw, 3.4rem);
                position: relative;
            }
            .studio-hero::after {
                background: rgba(255,255,255,.08);
                border-radius: 999px;
                content: "";
                height: 16rem;
                position: absolute;
                right: -5rem;
                top: -7rem;
                width: 16rem;
            }
            .studio-hero__eyebrow {
                color: #b8c9ff;
                font-size: .76rem;
                font-weight: 750;
                letter-spacing: .16em;
                text-transform: uppercase;
            }
            .studio-hero h1 {
                color: white;
                font-size: clamp(2.15rem, 5vw, 4rem);
                line-height: .98;
                margin: .75rem 0 1rem;
                max-width: 14ch;
            }
            .studio-hero p {
                color: #e7ecfb;
                font-size: 1.05rem;
                line-height: 1.6;
                margin: 0;
                max-width: 48rem;
            }
            [data-testid="stMetric"] {
                background: rgba(255,255,255,.94);
                border: 1px solid var(--studio-line);
                border-radius: 1rem;
                box-shadow: 0 8px 24px rgba(31, 45, 73, .05);
                height: 100%;
                min-height: 8.4rem;
                overflow: visible;
                padding: 1rem 1.1rem;
            }
            [data-testid="stMetricLabel"],
            [data-testid="stMetricValue"] {
                max-width: 100%;
                overflow: visible;
            }
            [data-testid="stMetricLabel"] p,
            [data-testid="stMetricValue"] > div {
                line-height: 1.2;
                overflow-wrap: anywhere;
                white-space: normal;
                word-break: normal;
            }
            [data-testid="stMetricValue"] > div {
                font-size: clamp(1.3rem, 2.15vw, 2rem);
            }
            .stButton > button,
            [data-testid="stBaseButton-secondary"] {
                background: #ffffff;
                border: 1px solid #9aa9bd;
                color: var(--studio-ink);
                font-weight: 700;
            }
            .stButton > button *,
            [data-testid="stBaseButton-secondary"] * {
                color: inherit !important;
            }
            .stButton > button:hover,
            [data-testid="stBaseButton-secondary"]:hover {
                background: #edf1ff;
                border-color: var(--studio-blue);
                color: #17358f;
            }
            [data-testid="stBaseButton-primary"] {
                background: var(--studio-blue);
                border-color: var(--studio-blue);
                color: #ffffff;
                font-weight: 750;
            }
            [data-testid="stBaseButton-primary"] * {
                color: #ffffff !important;
            }
            [data-testid="stVerticalBlockBorderWrapper"] {
                background: rgba(255,255,255,.9);
                border-color: var(--studio-line);
                border-radius: 1rem;
                box-shadow: 0 8px 24px rgba(31, 45, 73, .04);
            }
            .studio-kicker {
                color: var(--studio-blue);
                font-size: .73rem;
                font-weight: 800;
                letter-spacing: .12em;
                text-transform: uppercase;
            }
            .studio-step {
                align-items: flex-start;
                display: flex;
                gap: .8rem;
                margin: .8rem 0;
            }
            .studio-step__number {
                align-items: center;
                background: #e9edff;
                border-radius: 999px;
                color: var(--studio-blue);
                display: inline-flex;
                flex: 0 0 1.8rem;
                font-size: .8rem;
                font-weight: 800;
                height: 1.8rem;
                justify-content: center;
            }
            .studio-step__copy {
                color: var(--studio-muted);
                line-height: 1.45;
                padding-top: .15rem;
            }
            @media (max-width: 700px) {
                .block-container { padding-top: 1rem; }
                .studio-hero { border-radius: 1rem; }
                .studio-hero h1 { max-width: none; }
                [data-testid="stMetric"] { min-height: 7.5rem; }
                [data-testid="stMetricValue"] > div { font-size: 1.35rem; }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def normalise_teacher_display_name(value) -> str:
    """Return one safe, consistent teacher name/title for prompts and transcripts."""
    clean_name = " ".join(str(value or "").replace("\n", " ").split())
    return clean_name[:60] or "Teacher"


def get_teacher_display_name() -> str:
    """Read the shared teacher identity without creating another widget."""
    return normalise_teacher_display_name(
        st.session_state.get("teacher_display_name", "")
    )


def _normalise_optional_teacher_address(value) -> str:
    """Clean an optional pupil form of address without inventing a fallback."""
    return " ".join(str(value or "").replace("\n", " ").split())[:40]


def get_teacher_address_options(teacher_name=None) -> tuple[str, ...]:
    """Return the permitted ways pupils may address the current teacher."""
    primary_name = normalise_teacher_display_name(
        teacher_name if teacher_name is not None else get_teacher_display_name()
    )
    if not st.session_state.get("teacher_allow_alternative_address", False):
        return (primary_name,)

    alternative = _normalise_optional_teacher_address(
        st.session_state.get("teacher_alternative_address", "Sir")
    )
    if not alternative or alternative.casefold() == primary_name.casefold():
        return (primary_name,)
    return primary_name, alternative


def get_teacher_address_instruction(teacher_name=None) -> str:
    """Build consistent prompt guidance for realistic pupil forms of address."""
    addresses = get_teacher_address_options(teacher_name)
    primary_name = addresses[0]
    if len(addresses) == 1:
        return (
            f'The teacher is identified as "{primary_name}". If a pupil addresses '
            f'the teacher directly, use "{primary_name}" exactly and do not invent '
            "another title. Do not force a form of address into every response."
        )

    alternative = addresses[1]
    return (
        f'The teacher is identified in transcripts as "{primary_name}". When a pupil '
        f'addresses the teacher directly, they may naturally use either "{primary_name}" '
        f'or "{alternative}". Vary these across pupils and responses, while allowing '
        "many responses to use no form of address. Do not use any other name or title."
    )


def render_teacher_identity() -> str:
    """Render the single teacher-name control shared by all practice pages."""
    if "teacher_display_name" not in st.session_state:
        legacy_name = st.session_state.get("afl_teacher_name", "")
        st.session_state.teacher_display_name = (
            normalise_teacher_display_name(legacy_name)
            if str(legacy_name).strip()
            else ""
        )
    if "teacher_allow_alternative_address" not in st.session_state:
        st.session_state.teacher_allow_alternative_address = False
    if "teacher_alternative_address" not in st.session_state:
        st.session_state.teacher_alternative_address = "Sir"

    st.sidebar.divider()
    st.sidebar.text_input(
        "Teacher name/title",
        key="teacher_display_name",
        placeholder="e.g. Mr Smith, Miss Patel or Sir",
        help=(
            "This is the consistent teacher speaker label used throughout the "
            "practice tools."
        ),
    )
    st.sidebar.toggle(
        "Allow a second pupil address",
        key="teacher_allow_alternative_address",
        help=(
            "When enabled, pupils can naturally alternate between your recorded "
            "name/title and a shorter form such as Sir or Miss."
        ),
    )
    if st.session_state.teacher_allow_alternative_address:
        st.sidebar.text_input(
            "Alternative pupil address",
            key="teacher_alternative_address",
            placeholder="e.g. Sir or Miss",
        )

    teacher_name = get_teacher_display_name()
    address_labels = " or ".join(
        f"**{address}**"
        for address in get_teacher_address_options(teacher_name)
    )
    st.sidebar.caption(f"Pupils may address you as {address_labels}.")
    return teacher_name


def render_navigation() -> str:
    st.sidebar.markdown(
        f"""
        <div class="studio-brand">
            <div class="studio-brand__eyebrow">Teaching studio</div>
            <div class="studio-brand__name">{APP_SHORT_NAME}</div>
            <div class="studio-brand__tagline">{APP_TAGLINE}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    return st.sidebar.radio(
        "Workspace",
        NAV_ITEMS,
        format_func=lambda item: NAV_LABELS[item],
        key="studio_navigation",
    )


def render_sidebar_footer(on_refresh) -> None:
    st.sidebar.divider()
    if st.sidebar.button(
        "↻  Refresh cohort data",
        width="stretch",
        help="Reload the published cohort spreadsheets now.",
    ):
        on_refresh()
        st.rerun()
    st.sidebar.caption(f"Teaching Studio v{APP_VERSION} · Data cached for 5 minutes")


def render_home(
    cohorts: Mapping[str, pd.DataFrame],
    load_errors: Mapping[str, str],
) -> None:
    st.markdown(
        f"""
        <section class="studio-hero">
            <div class="studio-hero__eyebrow">Virtual classroom practice</div>
            <h1>Plan. Rehearse. Notice more.</h1>
            <p>{APP_NAME} brings pupil context, lesson rehearsal and live
            observation into one focused workspace for deliberate practice.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )

    metric_columns = st.columns(4)
    metric_columns[0].metric("Year 7", f"{len(cohorts['Year 7'])} students")
    metric_columns[1].metric("Year 10", f"{len(cohorts['Year 10'])} students")
    metric_columns[2].metric("Practice tools", "6 modes")
    metric_columns[3].metric("Classroom views", "4 views")

    for cohort, message in load_errors.items():
        st.warning(
            f"{cohort} data is temporarily unavailable. Use “Refresh cohort data” "
            f"when the published sheet is reachable again. ({message})"
        )

    st.markdown("## Choose the work you need to do")
    workflow_columns = st.columns(3)
    workflows = [
        (
            "01 · KNOW",
            "Know the class",
            "Search individual profiles, scan cohort passports and spot patterns before planning.",
            "Student Search · Year views · Analytics",
        ),
        (
            "02 · PLAN",
            "Shape the lesson",
            "Build a seating plan, stress-test one lesson or evaluate how learning develops across a sequence.",
            "Seating Plan · Lesson Stress-Tester · Sequence Evaluator",
        ),
        (
            "03 · REHEARSE",
            "Practise and notice",
            "Rehearse interactions, check understanding and circulate through simulated learning.",
            "Simulator · Academic AfL · Observe Learning",
        ),
    ]
    for column, (kicker, title, description, tools) in zip(workflow_columns, workflows):
        with column:
            with st.container(border=True):
                st.markdown(f'<div class="studio-kicker">{kicker}</div>', unsafe_allow_html=True)
                st.markdown(f"### {title}")
                st.write(description)
                st.caption(tools)

    left, right = st.columns([1.45, 1])
    with left:
        st.markdown("## A simple deliberate-practice loop")
        steps = [
            ("1", "Select the cohort, subject and class you will teach."),
            ("2", "Rehearse one precise part of the lesson, not the whole performance."),
            ("3", "Review what pupils did, adapt one move, then repeat."),
        ]
        for number, copy in steps:
            st.markdown(
                f"""
                <div class="studio-step">
                    <span class="studio-step__number">{number}</span>
                    <span class="studio-step__copy">{copy}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
    with right:
        st.markdown("## Before using AI practice")
        with st.container(border=True):
            st.write(
                "Student simulations use the configured Gemini key. Voice is optional "
                "and uses ElevenLabs when its key is present."
            )
            st.caption(
                "Keep live pupil data within your school’s approved environment and "
                "use simulations as rehearsal prompts, not as pupil judgements."
            )
