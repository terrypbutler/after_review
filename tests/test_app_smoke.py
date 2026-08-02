import importlib.util
import sys
import unittest
from unittest.mock import patch


STREAMLIT_AVAILABLE = (
    "streamlit" not in sys.modules
    and importlib.util.find_spec("streamlit") is not None
)


class AppSmokeTests(unittest.TestCase):
    @unittest.skipUnless(STREAMLIT_AVAILABLE, "Streamlit is not installed")
    def test_home_page_renders_with_cohort_data(self):
        from streamlit.testing.v1 import AppTest

        from modules import data_loader

        csv_payload = (
            b"Full Name,Form Group,Maths Set,SEN Status,EAL Status\n"
            b"Alex A,7A,M1,K,\n"
            b"Alice D,7B,M2,,Yes\n"
        )

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return csv_payload

        data_loader.load_data.clear()
        with patch.object(data_loader, "urlopen", return_value=FakeResponse()):
            app = AppTest.from_file("app.py", default_timeout=30)
            app.run()

        self.assertEqual(list(app.exception), [])
        self.assertEqual(app.sidebar.radio[0].value, "Home")
        self.assertEqual([metric.value for metric in app.metric[:2]], ["2 students", "2 students"])

        for page in [
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
            "Options",
        ]:
            with self.subTest(page=page):
                app.sidebar.radio[0].set_value(page)
                app.run()
                self.assertEqual(list(app.exception), [])


if __name__ == "__main__":
    unittest.main()
