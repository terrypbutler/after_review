# Butler Academy Teaching Studio

A Streamlit workspace for knowing a class, planning a lesson and rehearsing
high-leverage teaching moves with a virtual cohort.

## What is included

- Student search and cohort passports
- Cohort analytics and printable reports
- Seating planning with pupil-context indicators
- Virtual student roleplay
- Academic AfL rehearsal
- Lesson stress-testing
- Simulated circulation and learning observation

## Run locally

Use Python 3.11 or newer.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run app.py
```

For AI features, copy `.streamlit/secrets.toml.example` to
`.streamlit/secrets.toml` and add `GEMINI_API_KEY`, `OPENAI_API_KEY`, or both.
Use the app-wide sidebar toggle to choose the provider. The class-information
and planning views work without either key, and secrets should never be pasted
into the Python source.

To enable explicit seating-plan persistence, also configure
`SEATING_PLAN_STORAGE_PATH` in `secrets.toml`. The example uses the ignored
local `.data/` directory for development; deployments should point it at an
approved durable school storage mount. Printable HTML and JSON exports contain
pupil names and must remain inside the approved environment.

## Project shape

```text
app.py                       Main navigation and page composition
config.py                    App, cohort and subject configuration
modules/app_shell.py         Shared design system, navigation and home page
modules/class_setup.py       Reusable subject and class controls
modules/data_loader.py       Cached remote spreadsheet loading
modules/data_utils.py        Testable data normalisation and filters
modules/photo_utils.py       Cached pupil-photo processing
modules/*                    Existing teaching tools
photos/                      Local pupil images
tests/                       Fast tests for shared data behaviour
```

## Add the next feature

1. Put the feature’s rendering code in a focused module under `modules/`.
2. Add its label to `NAV_ITEMS` and `NAV_LABELS` in `modules/app_shell.py`.
3. Add one matching branch in `app.py`, reusing
   `render_subject_class_setup()` when the feature needs a class.
4. Keep spreadsheet cleanup and non-UI filters in `modules/data_utils.py` so
   they remain easy to test.

Do not commit `.streamlit/secrets.toml` or export pupil data outside the
school’s approved environment.
