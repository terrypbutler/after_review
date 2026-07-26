import streamlit as st
import os
from PIL import Image, ImageOps
from config import CACHE_TTL, PHOTO_FOLDER, PHOTO_HEIGHT, PHOTO_WIDTH


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_student_photo(name, cohort):
    """Load and crop a pupil photo once, then reuse it across Streamlit reruns."""
    if not os.path.isdir(PHOTO_FOLDER):
        return None

    safe_name = " ".join(str(name).strip().lower().split()).replace(".", "")
    filename = f"{safe_name}.png"
    files = {item.lower(): item for item in os.listdir(PHOTO_FOLDER)}
    matched_filename = files.get(filename)
    if not matched_filename:
        return None

    image_path = os.path.join(PHOTO_FOLDER, matched_filename)
    try:
        with Image.open(image_path) as source:
            image = source.copy()
        width, height = image.size
        top = int(height * 0.08)
        bottom = height - int(height * 0.13)
        crop = (
            (0, top, width // 2, bottom)
            if cohort == "Year 7"
            else (width // 2, top, width, bottom)
        )
        return ImageOps.fit(image.crop(crop), (PHOTO_WIDTH, PHOTO_HEIGHT))
    except (OSError, ValueError):
        return None

def display_student_photo(name, cohort):
    """
    Finds, crops, and displays the student's photo.
    Splits the image (Left for Y7, Right for Y10), trims the edges,
    and enforces a strict uniform size so all grid photos match perfectly.
    """
    if not os.path.exists(PHOTO_FOLDER):
        st.caption("No photo folder")
        return

    image = get_student_photo(name, cohort)
    if image is None:
        st.caption("Photo missing")
        return
    st.image(image, width=PHOTO_WIDTH)
