import unittest

import pandas as pd

from modules.simulation_options import (
    ATTAINMENT_FACTOR_COLUMN,
    ATTAINMENT_FACTOR_KEY,
    DEFAULT_SCORE_FACTOR,
    OPTIONS_STATE_VERSION,
    OPTIONS_STATE_VERSION_KEY,
    SCORE_FACTOR_KEYS,
    active_score_factor_summary,
    apply_attainment_factor,
    apply_score_factors,
    current_attainment_factor,
    current_score_factors,
    initialise_score_options,
)


class SimulationOptionTests(unittest.TestCase):
    def test_initialise_options_sets_neutral_defaults_without_overwriting(self):
        state = {
            "option_factor_confidence": 1.25,
            OPTIONS_STATE_VERSION_KEY: OPTIONS_STATE_VERSION,
        }

        initialise_score_options(state)

        self.assertEqual(state["option_factor_confidence"], 1.25)
        self.assertTrue(
            all(key in state for key in SCORE_FACTOR_KEYS.values())
        )
        self.assertEqual(state[ATTAINMENT_FACTOR_KEY], DEFAULT_SCORE_FACTOR)

    def test_initialise_options_centres_sliders_after_state_upgrade(self):
        state = {
            "option_factor_participation": 0.50,
            ATTAINMENT_FACTOR_KEY: 0.50,
        }

        initialise_score_options(state)

        self.assertEqual(state["option_factor_participation"], 1.00)
        self.assertEqual(state[ATTAINMENT_FACTOR_KEY], 1.00)
        self.assertEqual(
            state[OPTIONS_STATE_VERSION_KEY],
            OPTIONS_STATE_VERSION,
        )

    def test_scaling_changes_all_metrics_on_a_copy_and_caps_scores(self):
        source = pd.DataFrame(
            {
                "Full Name": ["Alex", "Sam"],
                "Participation Level": [80, 20],
                "Academic Confidence": [90, 40],
                "Processing Speed": [60, 50],
                "Independence": [70, ""],
            }
        )
        factors = {
            "Participation Level": 1.50,
            "Academic Confidence": 0.50,
            "Processing Speed": 1.25,
            "Independence": 1.50,
        }

        adjusted = apply_score_factors(source, factors)

        self.assertEqual(source["Participation Level"].tolist(), [80, 20])
        self.assertEqual(adjusted["Participation Level"].tolist(), [100, 30])
        self.assertEqual(adjusted["Academic Confidence"].tolist(), [45, 20])
        self.assertEqual(adjusted["Processing Speed"].tolist(), [75, 62])
        self.assertEqual(adjusted["Independence"].tolist(), [100, ""])

    def test_attainment_factor_is_attached_without_changing_grades(self):
        source = pd.DataFrame(
            {
                "Full Name": ["Alex", "Sam"],
                "Maths Predicted Grade": ["8", "3"],
            }
        )

        adjusted = apply_attainment_factor(source, 0.75)

        self.assertNotIn(ATTAINMENT_FACTOR_COLUMN, source.columns)
        self.assertEqual(
            adjusted[ATTAINMENT_FACTOR_COLUMN].tolist(),
            [0.75, 0.75],
        )
        self.assertEqual(adjusted["Maths Predicted Grade"].tolist(), ["8", "3"])

    def test_invalid_and_out_of_range_state_is_safely_normalised(self):
        state = {
            "option_factor_participation": 9,
            "option_factor_confidence": "not-a-number",
            "option_factor_processing": 0,
        }

        factors = current_score_factors(state)

        self.assertEqual(factors["Participation Level"], 1.50)
        self.assertEqual(factors["Academic Confidence"], DEFAULT_SCORE_FACTOR)
        self.assertEqual(factors["Processing Speed"], 0.50)
        self.assertEqual(factors["Independence"], DEFAULT_SCORE_FACTOR)
        self.assertEqual(
            active_score_factor_summary(state),
            ["Participation Level: 1.50×", "Processing Speed: 0.50×"],
        )

    def test_attainment_factor_is_bounded_and_included_in_status(self):
        state = {ATTAINMENT_FACTOR_KEY: 2}

        self.assertEqual(current_attainment_factor(state), 1.50)
        self.assertEqual(
            active_score_factor_summary(state),
            ["Attainment / answer success: 1.50×"],
        )


if __name__ == "__main__":
    unittest.main()
