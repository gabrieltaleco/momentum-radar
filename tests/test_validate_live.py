import json
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import validate_live  # noqa: E402
import momentum_tool  # noqa: E402


class ValidateLiveTests(unittest.TestCase):
    def test_validation_report_fails_on_critical_provider(self):
        config = momentum_tool.load_config(Path(__file__).resolve().parents[1] / "config.json")
        config_path = Path(tempfile.mktemp(suffix=".json"))
        output_dir = Path(tempfile.mkdtemp())
        try:
            config_path.write_text(json.dumps(config), encoding="utf-8")
            provider_quality = [{"symbol": "GLOBAL", "source": "alpha_vantage", "rows": 0, "status": "ERRO", "message": "fixture"}]
            with patch.object(validate_live, "fetch_live_data", return_value=([], provider_quality, {"news_scores": {}, "macro_score": 50.0})):
                with patch.object(validate_live.sys, "argv", ["validate_live.py", "--config", str(config_path), "--output-dir", str(output_dir)]):
                    result = validate_live.main()
            self.assertEqual(result, 2)
            report = json.loads((output_dir / "live-validation.json").read_text(encoding="utf-8"))
            self.assertFalse(report["passed"])
        finally:
            config_path.unlink(missing_ok=True)
            for child in output_dir.iterdir():
                child.unlink()
            output_dir.rmdir()


if __name__ == "__main__":
    unittest.main()
