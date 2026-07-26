import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from modules.data_utils import count_active, filter_exact, prepare_data, safe_unique


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


if __name__ == "__main__":
    unittest.main()
