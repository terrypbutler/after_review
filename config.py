APP_NAME = "Butler Academy Teaching Studio"
APP_SHORT_NAME = "Butler Academy"
APP_TAGLINE = "Know the class. Rehearse the lesson. Notice more."
APP_VERSION = "0.8"

# Fast model for short, interactive pupil and mentor responses.
REACTION_MODEL = "gemini-3.5-flash-lite"

# More capable model for complex lesson-plan analysis.
ANALYSIS_MODEL = "gemini-3.6-flash"

# OpenAI equivalents used when OpenAI is selected on the Options page. The
# interactive model balances responsiveness and cost; the analysis model is
# reserved for the two deeper lesson-review tools.
OPENAI_REACTION_MODEL = "gpt-5.6-terra"
OPENAI_ANALYSIS_MODEL = "gpt-5.6-sol"

SPREADSHEET_ID = "1suZQlbQxzt8gJm_hTdBYoQAmz-TgkHq57I_sXwlvCME"
YEAR_7_URL = (
    f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export"
    "?format=csv&gid=0"
)
YEAR_10_URL = (
    f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export"
    "?format=csv&gid=214766920"
)

COHORT_URLS = {
    "Year 7": YEAR_7_URL,
    "Year 10": YEAR_10_URL,
}

SUBJECTS = [
    "Maths",
    "Science",
    "English",
    "Art",
    "Computing",
    "Design",
    "Drama",
    "Geography",
    "History",
    "Hospitality",
    "Music",
    "Photography",
    "Spanish",
    "Sport",
]

PHOTO_FOLDER = "photos"
PHOTO_WIDTH = 140
PHOTO_HEIGHT = 185

# Streamlit reruns frequently. Five minutes keeps the app responsive without
# repeatedly downloading the same cohort data and reprocessing large photos.
CACHE_TTL = 300

COLUMNS_TO_HIDE = [
    "Picture",
    "First Name",
    "Surname Initial",
    "Student ID"
]

FIELD_MAP = {
    "form_group": [
        "Form Tutor",
        "Tutor",
        "Form Group",
        "Tutor Group"
    ],

    "gender": [
        "Gender"
    ],

    "sen_status": [
        "SEN Status",
        "SEND Status"
    ],

    "sen_detail": [
        "SEND detail",
        "SEN detail"
    ],

    "ethnicity": [
        "Ethnicity"
    ],

    "eal": [
        "EAL",
        "EAL Status"
    ],

    "pp": [
        "Premium",
        "Disadvantaged (PP)",
        "Pupil Premium"
    ],

    "reading": [
        "SATs Reading",
        "SAT's Reading",
        "Reading Score"
    ],

    "maths": [
        "SATs Maths",
        "SAT's Maths",
        "Maths Score"
    ]
}

COLUMN_ALIASES = {
    "SAT's Maths": "SATs Maths",
    "Maths Score": "SATs Maths",
    "SAT's Reading": "SATs Reading",
    "Reading Score": "SATs Reading"
}
