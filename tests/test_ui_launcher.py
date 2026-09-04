import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class UiLauncherTests(unittest.TestCase):
    def test_launcher_does_not_shadow_powershell_host_variable(self):
        script = (ROOT / "run-ui.ps1").read_text(encoding="utf-8")
        self.assertNotIn("[string]$Host", script)
        self.assertIn("[string]$ListenHost", script)
        self.assertIn("--host $ListenHost", script)

    def test_local_notifications_are_explicit_and_browser_only(self):
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="enable-notifications"', html)
        self.assertIn("Notification.requestPermission()", javascript)
        self.assertIn("radar:local-notifications", javascript)
        self.assertNotIn("/api/notification", javascript)

    def test_alert_center_has_local_search_and_sort_controls(self):
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="alert-search"', html)
        self.assertIn('id="alert-sort"', html)
        self.assertIn('id="export-alerts-report"', html)
        self.assertIn("ui.alertQuery", javascript)
        self.assertIn("ui.alertSort", javascript)
        self.assertIn("radar-supervisao-", javascript)

    def test_decision_brief_and_automation_health_are_visible(self):
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="decision-brief"', html)
        self.assertIn('id="decision-brief-status"', html)
        self.assertIn("state.automation", javascript)
        self.assertIn("última ronda falhou", javascript)

    def test_rotating_cohort_is_distinguished_from_provider_errors(self):
        javascript = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.assertIn("FORA_DA_COORTE", javascript)
        self.assertIn("Fora da coorte", javascript)


if __name__ == "__main__":
    unittest.main()
