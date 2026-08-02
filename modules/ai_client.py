"""Provider-neutral adapter for Gemini and OpenAI model calls.

The teaching tools use the small ``GenerativeModel`` interface below so the
sidebar provider choice can apply consistently without duplicating API logic.
"""

import base64
from dataclasses import dataclass
from io import BytesIO

from PIL import Image

from config import (
    ANALYSIS_MODEL,
    OPENAI_ANALYSIS_MODEL,
    OPENAI_REACTION_MODEL,
)


GEMINI_PROVIDER = "Gemini"
OPENAI_PROVIDER = "OpenAI"
PROVIDER_TOGGLE_KEY = "use_openai_provider"
PROVIDER_OPTION_KEY = "ai_provider_option"

_provider = GEMINI_PROVIDER
_gemini_client = None
_openai_client = None


@dataclass
class ModelResponse:
    """Common response shape used by the existing teaching tools."""

    text: str

    @property
    def parts(self):
        return [self.text] if self.text else []


def selected_provider() -> str:
    """Return the provider currently selected in Streamlit session state."""
    import streamlit as st

    selected_option = st.session_state.get(PROVIDER_OPTION_KEY)
    if selected_option in {GEMINI_PROVIDER, OPENAI_PROVIDER}:
        return selected_option
    return (
        OPENAI_PROVIDER
        if st.session_state.get(PROVIDER_TOGGLE_KEY, False)
        else GEMINI_PROVIDER
    )


def provider_name() -> str:
    """Return the configured provider for user-facing status and errors."""
    return _provider


def render_provider_options() -> str:
    """Render the app-wide Gemini/OpenAI selector on the Options page."""
    import streamlit as st

    if PROVIDER_OPTION_KEY not in st.session_state:
        st.session_state[PROVIDER_OPTION_KEY] = selected_provider()
    provider = st.radio(
        "AI provider",
        [GEMINI_PROVIDER, OPENAI_PROVIDER],
        horizontal=True,
        key=PROVIDER_OPTION_KEY,
        help="Switches every AI-powered teaching tool for this browser session.",
    )
    st.session_state[PROVIDER_TOGGLE_KEY] = provider == OPENAI_PROVIDER
    if provider == OPENAI_PROVIDER:
        st.caption(
            f"Using OpenAI · {OPENAI_REACTION_MODEL} for interactive work · "
            f"{OPENAI_ANALYSIS_MODEL} for deeper analysis"
        )
    else:
        st.caption("Using Gemini with the existing app model settings")
    return provider


def render_provider_status() -> None:
    """Show the current provider in the sidebar without duplicating its control."""
    import streamlit as st

    st.sidebar.divider()
    st.sidebar.markdown("### AI provider")
    st.sidebar.caption(
        f"Current: **{selected_provider()}** · Change this on the Options page."
    )


def configure(provider: str, api_key: str) -> None:
    """Configure one provider without reading or persisting the API key."""
    global _provider, _gemini_client, _openai_client

    if provider == OPENAI_PROVIDER:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "The OpenAI SDK is not installed. Run pip install -r requirements.txt."
            ) from exc
        _openai_client = OpenAI(api_key=api_key)
    elif provider == GEMINI_PROVIDER:
        try:
            from google import genai
        except ImportError as exc:
            raise RuntimeError(
                "The Google Gen AI SDK is not installed. Run pip install -r requirements.txt."
            ) from exc
        _gemini_client = genai.Client(api_key=api_key)
    else:
        raise ValueError(f"Unsupported AI provider: {provider}")

    _provider = provider


def configure_selected_provider(show_error: bool = True) -> bool:
    """Configure the sidebar-selected provider from Streamlit secrets."""
    import streamlit as st
    from modules.app_secrets import get_secret

    global _provider
    provider = selected_provider()
    _provider = provider
    secret_name = (
        "OPENAI_API_KEY" if provider == OPENAI_PROVIDER else "GEMINI_API_KEY"
    )
    api_key = get_secret(secret_name)
    if not api_key:
        if show_error:
            st.error(
                f"⚠️ {provider} API key missing. Add {secret_name} to "
                ".streamlit/secrets.toml."
            )
        return False

    try:
        configure(provider, api_key)
    except (RuntimeError, ValueError) as exc:
        if show_error:
            st.error(f"⚠️ {exc}")
        return False
    return True


def _openai_model_name(requested_model: str) -> str:
    if requested_model == ANALYSIS_MODEL:
        return OPENAI_ANALYSIS_MODEL
    return OPENAI_REACTION_MODEL


def _image_data_url(image: Image.Image) -> str:
    output = BytesIO()
    image_format = (image.format or "PNG").upper()
    if image_format not in {"PNG", "JPEG", "WEBP", "GIF"}:
        image_format = "PNG"
    image.save(output, format=image_format)
    mime_format = "jpeg" if image_format == "JPEG" else image_format.lower()
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/{mime_format};base64,{encoded}"


def _openai_input(contents):
    items = contents if isinstance(contents, (list, tuple)) else [contents]
    content_parts = []
    for item in items:
        if isinstance(item, Image.Image):
            content_parts.append(
                {
                    "type": "input_image",
                    "image_url": _image_data_url(item),
                    "detail": "auto",
                }
            )
        else:
            content_parts.append({"type": "input_text", "text": str(item)})
    return [{"role": "user", "content": content_parts}]


class GenerativeModel:
    """Compatibility interface used by every AI-backed teaching feature."""

    def __init__(self, model_name: str):
        self.model_name = model_name

    def generate_content(self, contents, generation_config=None):
        if _provider == OPENAI_PROVIDER:
            if _openai_client is None:
                raise RuntimeError("OpenAI has not been configured with an API key.")

            analysis_request = self.model_name == ANALYSIS_MODEL
            text_config = {
                "verbosity": "medium" if analysis_request else "low"
            }
            if (
                generation_config
                and generation_config.get("response_mime_type")
                == "application/json"
            ):
                text_config["format"] = {"type": "json_object"}
            response = _openai_client.responses.create(
                model=_openai_model_name(self.model_name),
                input=_openai_input(contents),
                reasoning={"effort": "medium" if analysis_request else "low"},
                text=text_config,
                store=False,
            )
            return ModelResponse(text=response.output_text or "")

        if _gemini_client is None:
            raise RuntimeError("Gemini has not been configured with an API key.")
        return _gemini_client.models.generate_content(
            model=self.model_name,
            contents=contents,
            config=generation_config,
        )
