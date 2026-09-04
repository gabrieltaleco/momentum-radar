import itertools
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app_server
from src.action_commentary import action_commentary, commentary_entries, COMMENTARY_TITLE
from src.pdf_report import ascii_text, build_asset_pdf, build_daily_pdf, build_portfolio_pdf


class ActionCommentaryTests(unittest.TestCase):
    def setUp(self):
        self.asset = {"symbol": "TEST", "name": "Test asset"}
        self.signal = {"symbol": "TEST", "date": "2026-09-03", "score": 85,
                       "action": "Considerar compra", "momentum": 70, "trend": 60,
                       "relative_strength": 55, "volume": 40}
        self.meta = {"as_of": "2026-09-03", "mode": "live", "context_available": True, "benchmark_available": True}
        self.quality = {"symbol": "TEST", "status": "OK"}

    def test_action_variants_and_limit(self):
        actions = {"Considerar compra": "entrada faseada", "Manter/observar": "manteria sob revisão",
                   "Reduzir/evitar": "evitaria entrar", "Não agir": "Esperaria"}
        for action, phrase in actions.items():
            text = action_commentary(self.asset, dict(self.signal, action=action), self.quality, self.meta)
            self.assertIn(phrase, text)
            self.assertIn("volume (40.0/100)", text)
            self.assertLessEqual(len(text.split()), 150)

    def test_missing_stale_and_demo_never_suggest_entry(self):
        for status, score, mode in itertools.product(["OK", "ATRASADO", "ERRO", ""], [None, float("nan"), float("inf"), 101, -1, 85], ["demo", "live"]):
            text = action_commentary(self.asset, dict(self.signal, score=score), {"status": status}, dict(self.meta, mode=mode))
            self.assertLessEqual(len(text.split()), 150)
            if status != "OK" or score != 85 or mode != "live":
                self.assertNotIn("Estudaria uma entrada", text)
        self.assertIn("fonte está atrasada", action_commentary(self.asset, self.signal, {"status": "ATRASADO"}, self.meta))

    def test_position_result_and_incomplete_context(self):
        for pnl in [-0.5, 0.0, 0.5]:
            position = {"acquisition_analysis": {"available": True, "pnl_pct": pnl}}
            text = action_commentary(self.asset, self.signal, self.quality, self.meta, position)
            self.assertLessEqual(len(text.split()), 150)
            self.assertIn(f"{pnl:+.1%}", text)
        text = action_commentary(self.asset, self.signal, self.quality, dict(self.meta, context_available=False))
        self.assertIn("falta contexto", text)
        self.assertNotIn("Estudaria uma entrada", text)

    def test_old_or_future_signal_overrides_ok_quality(self):
        for date in ["2026-08-05", "2026-09-05", "invalid"]:
            text = action_commentary(self.asset, dict(self.signal, date=date), self.quality, self.meta)
            self.assertNotIn("Estudaria uma entrada", text)
            self.assertIn("Não abriria", text)

    def test_all_assets_and_pdf_markdown_share_text_without_network(self):
        state = {"meta": self.meta, "signals": [self.signal], "quality": [self.quality],
                 "catalog": [self.asset], "portfolio": {"positions": [{"symbol": "TEST"}, {"symbol": "MISSING"}]}}
        with patch("urllib.request.urlopen", side_effect=AssertionError("No network")):
            entries = commentary_entries(state, portfolio_only=True)
            self.assertEqual([s for s, _ in entries], ["TEST", "MISSING"])
            with patch.object(app_server, "load_state", return_value=state):
                _, md = app_server.markdown_report("TEST")
                _, portfolio_md = app_server.portfolio_markdown_report()
            self.assertIn(COMMENTARY_TITLE, md)
            for _, text in entries:
                self.assertIn(text, portfolio_md)
            asset_pdf = build_asset_pdf(self.asset, self.signal, self.quality, self.meta, {}, position=state["portfolio"]["positions"][0])
            for pdf in [asset_pdf, build_daily_pdf(state), build_portfolio_pdf(state)]:
                self.assertIn(b"Como agiria nesta situacao", pdf)
            # PDF wraps the paragraph into several strings; compare normalized text fragments.
            self.assertIn(b"entrada faseada", asset_pdf)
            self.assertIn(entries[0][1], md)

    def test_daily_markdown_generation_includes_commentary(self):
        import json
        from src.momentum_tool import write_report
        payload = json.loads((app_server.OUTPUT_DIR / "momentum_data.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary, patch("urllib.request.urlopen", side_effect=AssertionError("No network")):
            destination = Path(temporary) / "report.md"
            write_report(payload, destination)
            content = destination.read_text(encoding="utf-8")
            for _, paragraph in commentary_entries(payload):
                self.assertIn(paragraph, content)
                self.assertLessEqual(len(paragraph.split()), 150)


if __name__ == "__main__":
    unittest.main()
