import importlib.util
import unittest


try:
    GENAI_AVAILABLE = importlib.util.find_spec("google.genai") is not None
except ModuleNotFoundError:
    GENAI_AVAILABLE = False


class GeminiClientTests(unittest.TestCase):
    @unittest.skipUnless(GENAI_AVAILABLE, "google-genai is not installed")
    def test_adapter_forwards_model_contents_and_config(self):
        from modules import gemini_client

        captured = {}

        class FakeModels:
            def generate_content(self, **kwargs):
                captured.update(kwargs)
                return "response"

        class FakeClient:
            models = FakeModels()

        gemini_client._client = FakeClient()
        try:
            response = gemini_client.GenerativeModel("gemini-test").generate_content(
                ["prompt"],
                generation_config={"response_mime_type": "application/json"},
            )
        finally:
            gemini_client._client = None

        self.assertEqual(response, "response")
        self.assertEqual(
            captured,
            {
                "model": "gemini-test",
                "contents": ["prompt"],
                "config": {"response_mime_type": "application/json"},
            },
        )


if __name__ == "__main__":
    unittest.main()
