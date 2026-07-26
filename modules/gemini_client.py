"""Small compatibility layer around Google's current Gen AI SDK.

Keeping model calls behind this module gives future features one stable place
for client setup, model defaults, retries, and structured-output behaviour.
"""

from google import genai


_client = None


def configure(api_key: str) -> None:
    global _client
    _client = genai.Client(api_key=api_key)


class GenerativeModel:
    """Minimal adapter for the model interface used by the teaching tools."""

    def __init__(self, model_name: str):
        self.model_name = model_name

    def generate_content(self, contents, generation_config=None):
        if _client is None:
            raise RuntimeError("Gemini has not been configured with an API key.")

        return _client.models.generate_content(
            model=self.model_name,
            contents=contents,
            config=generation_config,
        )
