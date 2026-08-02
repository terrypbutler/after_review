import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from modules.data_utils import (
    count_active,
    filter_exact,
    get_ai_response_profile,
    prepare_data,
    safe_unique,
    suggest_working_group,
)


class PrepareDataTests(unittest.TestCase):
    def test_normalises_aliases_coalesces_duplicates_and_hides_ids(self):
        source = pd.DataFrame(
            {
                " Full Name ": ["  Alex   A  ", "Alice D"],
                "SAT's Maths": [103, None],
                "Maths Score": [None, 111],
                "Student ID": ["private-1", "private-2"],
                "Unnamed: 9": ["", ""],
            }
        )

        result = prepare_data(source)

        self.assertEqual(result["Full Name"].tolist(), ["Alex A", "Alice D"])
        self.assertEqual(result["SATs Maths"].tolist(), [103, 111])
        self.assertNotIn("Student ID", result.columns)
        self.assertNotIn("Unnamed: 9", result.columns)


class FilterTests(unittest.TestCase):
    def setUp(self):
        self.df = pd.DataFrame(
            {
                "Full Name": ["Alex", "Alice", "Amelia"],
                "Form Group": ["7A", "7B", "7A"],
                "SEN Status": ["K", "", "No"],
            }
        )

    def test_safe_unique_returns_clean_sorted_values(self):
        self.assertEqual(safe_unique(self.df, "Form Group"), ["7A", "7B"])
        self.assertEqual(safe_unique(self.df, "Missing"), [])

    def test_filter_exact_supports_one_or_many_values(self):
        self.assertEqual(
            filter_exact(self.df, "Form Group", "7A")["Full Name"].tolist(),
            ["Alex", "Amelia"],
        )
        self.assertEqual(
            filter_exact(self.df, "Form Group", ["7B"])["Full Name"].tolist(),
            ["Alice"],
        )

    def test_count_active_ignores_negative_markers(self):
        self.assertEqual(count_active(self.df, ["SEND Status", "SEN Status"]), 1)


class AiResponseProfileTests(unittest.TestCase):
    def test_prefers_sheet_profile_and_adds_short_subject_evidence(self):
        row = pd.Series(
            {
                "AI Response Profile": "Alex | Year 7 | confidence 42/100",
                "Participation Level": 35,
                "Academic Confidence": 60,
                "Processing Speed": 70,
                "Independence": 55,
                "Maths": (
                    "Alex is working securely at the expected standard. "
                    "A strength is explaining multiplication. "
                    "This third sentence should not be sent."
                ),
            }
        )

        profile = get_ai_response_profile(row, "Year 7", "Maths")

        self.assertIn("Alex | Year 7 | confidence 42/100", profile)
        self.assertIn(
            "Current scenario metrics (authoritative for this run; ignore earlier "
            "metric numbers): participation 35/100, academic confidence 60/100, "
            "processing speed 70/100, independence 55/100",
            profile,
        )
        self.assertIn("A strength is explaining multiplication.", profile)
        self.assertNotIn("This third sentence", profile)

    def test_fallback_excludes_home_and_safeguarding_narrative(self):
        row = pd.Series(
            {
                "Full Name": "Sam P.",
                "Participation Level": 37,
                "Academic Confidence": 41,
                "Typical Learning Barrier": "Rushes multi-step work.",
                "Home Life & Interests": "Sensitive home and safeguarding detail.",
            }
        )

        profile = get_ai_response_profile(row, "Year 7")

        self.assertIn("participation 37", profile)
        self.assertIn("Barrier: Rushes multi-step work.", profile)
        self.assertNotIn("Sensitive home", profile)

    def test_fallback_handles_missing_spreadsheet_values(self):
        row = pd.Series(
            {
                "Full Name": "Alex A.",
                "Participation Level": pd.NA,
                "EAL Status": None,
            }
        )

        profile = get_ai_response_profile(row, "Year 7")

        self.assertIn("Alex A. | Year 7", profile)
        self.assertNotIn("<NA>", profile)


class WorkingGroupTests(unittest.TestCase):
    def setUp(self):
        self.students = pd.DataFrame(
            [
                {
                    "Full Name": "Alex A.",
                    "Form Group": "10A",
                    "Preferred Peers": "Sam B.; Lee D.",
                    "Pairing Considerations": "Lee D.",
                    "Peer Discussion Style": "Quiet listener",
                    "Academic Confidence": 30,
                    "Independence": 35,
                },
                {
                    "Full Name": "Sam B.",
                    "Form Group": "10A",
                    "Preferred Peers": "Alex A.",
                    "Pairing Considerations": "",
                    "Peer Discussion Style": "Collaborative",
                    "Academic Confidence": 65,
                    "Independence": 70,
                },
                {
                    "Full Name": "Jordan C.",
                    "Form Group": "10A",
                    "Preferred Peers": "",
                    "Pairing Considerations": "",
                    "Peer Discussion Style": "Collaborative",
                    "Academic Confidence": 55,
                    "Independence": 60,
                },
                {
                    "Full Name": "Lee D.",
                    "Form Group": "10A",
                    "Preferred Peers": "Alex A.",
                    "Pairing Considerations": "",
                    "Peer Discussion Style": "Takes control",
                    "Academic Confidence": 70,
                    "Independence": 75,
                },
                {
                    "Full Name": "Pat E.",
                    "Form Group": "10B",
                    "Preferred Peers": "",
                    "Pairing Considerations": "Alex A.",
                    "Peer Discussion Style": "Collaborative",
                    "Academic Confidence": 60,
                    "Independence": 65,
                },
            ]
        )

    def test_prioritises_preference_and_excludes_concerns_both_ways(self):
        group = suggest_working_group(
            self.students.iloc[0],
            self.students,
            group_size=3,
        )

        self.assertEqual(group, ["Sam B.", "Jordan C."])
        self.assertNotIn("Lee D.", group)
        self.assertNotIn("Pat E.", group)

    def test_uses_only_the_current_filtered_class(self):
        filtered = self.students[
            self.students["Full Name"].isin(["Alex A.", "Jordan C."])
        ]

        group = suggest_working_group(
            self.students.iloc[0],
            filtered,
            group_size=4,
        )

        self.assertEqual(group, ["Jordan C."])


if __name__ == "__main__":
    unittest.main()
