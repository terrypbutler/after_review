from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd
import streamlit as st

from config import CACHE_TTL
from modules.data_utils import prepare_data


class DataLoadError(RuntimeError):
    """Raised when a cohort spreadsheet cannot be loaded or validated."""


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_data(url):
    """Fetch and normalise one published cohort spreadsheet."""
    request = Request(url, headers={"User-Agent": "Butler-Academy-Teaching-Studio/0.8"})
    try:
        with urlopen(request, timeout=15) as response:
            payload = response.read()
        df = prepare_data(pd.read_csv(BytesIO(payload)))
    except (HTTPError, URLError, TimeoutError, OSError, pd.errors.ParserError) as exc:
        raise DataLoadError("the published spreadsheet could not be reached") from exc

    if "Full Name" not in df.columns:
        raise DataLoadError("the spreadsheet is missing its Full Name column")

    return df
