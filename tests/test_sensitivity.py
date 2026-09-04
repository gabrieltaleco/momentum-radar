import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import momentum_tool  # noqa: E402
from sensitivity import run_sensitivity  # noqa: E402


class SensitivityTests(unittest.TestCase):
    def test_grid_is_deterministic_and_contains_base_scenario(self):
        config = momentum_tool.load_config(Path(__file__).resolve().parents[1] / "config.json")
        full_rows = momentum_tool.generate_demo_data(config)
        dates = sorted({row["date"] for row in full_rows})[-230:]
        rows = [row for row in full_rows if row["date"] in dates]
        first = run_sensitivity(config, rows)
        second = run_sensitivity(config, rows)
        self.assertEqual(first["scenario_count"], 108)
        self.assertEqual(first["scenarios"], second["scenarios"])
        self.assertTrue(any(row["buy_score"] == 80 and row["min_confidence"] == 55 and row["signal_delay_days"] == 1 for row in first["scenarios"]))
        self.assertEqual(sorted({row["total_cost_bps"] for row in first["scenarios"]}), [0, 6, 12])
        self.assertEqual(sorted({row["buy_score"] for row in first["scenarios"]}), [70, 75, 80, 85])
        self.assertIn("median_cagr", first["summary"])


if __name__ == "__main__":
    unittest.main()
