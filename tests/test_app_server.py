import json
import tempfile
import unittest
import datetime as dt
import os
from pathlib import Path
from unittest.mock import patch

import app_server


class PortfolioReportHighlightTests(unittest.TestCase):
    def test_report_highlights_only_sectors_and_positions_at_threshold(self):
        state = {
            "thresholds": {"buy_score": 80},
            "sector_summary": [
                {"sector": "Forte", "average_score": 80, "signals": 2, "buy_signals": 1},
                {"sector": "Abaixo", "average_score": 79.9, "signals": 3, "buy_signals": 0},
            ],
            "portfolio": {"positions": [
                {"symbol": "GOOD", "sector": "Forte", "score": 81, "weight": 0.2, "action": "Manter"},
                {"symbol": "WATCH", "sector": "Abaixo", "score": 79.9, "weight": 0.1, "action": "Aguardar"},
            ]},
        }

        threshold, sectors, positions = app_server.portfolio_report_highlights(state)

        self.assertEqual(threshold, 80)
        self.assertEqual([item["sector"] for item in sectors], ["Forte"])
        self.assertEqual([item["symbol"] for item in positions], ["GOOD"])
        self.assertEqual(sectors[0]["portfolio_count"], 1)


class AppServerStateTests(unittest.TestCase):
    def test_weekend_freshness_does_not_flag_normal_market_closure(self):
        now = dt.datetime(2026, 8, 16, 12, tzinfo=dt.timezone.utc)
        result = app_server.snapshot_freshness("2026-08-14T22:00:00+00:00", now)
        self.assertTrue(result["weekend"])
        self.assertFalse(result["stale"])
        self.assertEqual(result["threshold_hours"], 72.0)

    def test_weekend_freshness_still_flags_genuinely_old_snapshot(self):
        now = dt.datetime(2026, 8, 16, 12, tzinfo=dt.timezone.utc)
        result = app_server.snapshot_freshness("2026-08-13T00:00:00+00:00", now)
        self.assertTrue(result["stale"])

    def test_portfolio_monitor_queue_explains_why_assets_are_next(self):
        queue = app_server.load_state()["portfolio_monitor"]["next_queue"]
        self.assertTrue(queue)
        self.assertTrue(all(item.get("symbol") and item.get("reason") for item in queue))
        self.assertTrue(all(item.get("reason") == "sem leitura local" or item.get("last_read") for item in queue))

    def test_automation_history_reads_terminal_runs_without_exposing_extra_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            history_path = Path(directory) / "automation-history.jsonl"
            history_path.write_text(
                json.dumps({"run_id": "one", "state": "completed", "started_at": "a", "completed_at": "b", "mode": "live", "exit_code": 0}) + "\n"
                + json.dumps({"run_id": "two", "state": "failed", "started_at": "c", "completed_at": "d", "mode": "live", "exit_code": 1, "error": "provider"}) + "\n",
                encoding="utf-8",
            )
            with patch.object(app_server, "AUTOMATION_HISTORY_PATH", history_path):
                history = app_server.automation_history_snapshot()
        self.assertTrue(history["available"])
        self.assertEqual(history["recorded_runs"], 2)
        self.assertEqual(history["failed_runs"], 1)
        self.assertEqual(history["runs"][0]["run_id"], "two")
        self.assertNotIn("api_key", history["runs"][0])

    def test_portfolio_action_separates_existing_position_from_new_entry(self):
        self.assertEqual(app_server.portfolio_action("Reduzir/evitar", True), "Reduzir/vender")
        self.assertEqual(app_server.portfolio_action("Reduzir/evitar", False), "Evitar")
        self.assertEqual(app_server.portfolio_action("Manter/observar", False), "Manter/observar")

    def test_portfolio_correlation_pairs_uses_common_daily_returns(self):
        dates = [(dt.date(2026, 1, 1) + dt.timedelta(days=index)).isoformat() for index in range(25)]
        history = []
        for index, date_value in enumerate(dates):
            history.extend([
                {"symbol": "A", "date": date_value, "close": 100.0 + index},
                {"symbol": "B", "date": date_value, "close": 200.0 + index * 2},
            ])
        pairs = app_server.portfolio_correlation_pairs([{"symbol": "A"}, {"symbol": "B"}], {"history": history})
        self.assertEqual(pairs[0]["left"], "A")
        self.assertGreater(pairs[0]["correlation"], 0.99)

    def test_portfolio_risk_contribution_uses_local_covariance(self):
        dates = [(dt.date(2026, 1, 1) + dt.timedelta(days=index)).isoformat() for index in range(30)]
        history = []
        for index, date_value in enumerate(dates):
            history.extend([
                {"symbol": "A", "date": date_value, "close": 100.0 + index},
                {"symbol": "B", "date": date_value, "close": 200.0 + index * 3},
            ])
        result = app_server.portfolio_risk_contribution(
            [{"symbol": "A", "weight": 0.6}, {"symbol": "B", "weight": 0.4}],
            {"history": history},
        )
        self.assertEqual(result["observations"], 29)
        self.assertEqual({item["symbol"] for item in result["rows"]}, {"A", "B"})
        self.assertAlmostEqual(sum(item["contribution_pct"] for item in result["rows"]), 1.0, places=5)
        self.assertGreater(result["annualized_volatility"], 0)

    def test_portfolio_sector_drift_marks_over_and_underweight(self):
        rows = app_server.portfolio_sector_drift(
            [{"sector": "Energia", "weight": 0.70}, {"sector": "Tecnologia", "weight": 0.30}],
            {"Energia": 0.50, "Tecnologia": 0.50},
            1000.0,
        )
        by_sector = {item["sector"]: item for item in rows}
        self.assertEqual(by_sector["Energia"]["status"], "acima")
        self.assertEqual(by_sector["Tecnologia"]["status"], "abaixo")
        self.assertAlmostEqual(by_sector["Energia"]["value_gap"], 200.0)

    def test_compare_snapshots_returns_local_score_and_action_deltas(self):
        history = [
            {"symbol": "SPY", "as_of": "2026-08-12", "score": 60, "action": "Manter/observar"},
            {"symbol": "GLD", "as_of": "2026-08-12", "score": 70, "action": "Manter/observar"},
            {"symbol": "SPY", "as_of": "2026-08-13", "score": 74, "action": "Considerar compra"},
            {"symbol": "GLD", "as_of": "2026-08-13", "score": 65, "action": "Manter/observar"},
        ]
        comparison = app_server.compare_snapshots(history)
        self.assertTrue(comparison["available"])
        self.assertEqual(comparison["action_changes"], 1)
        self.assertEqual(comparison["rows"][0]["symbol"], "SPY")
        self.assertEqual(comparison["rows"][0]["score_delta"], 14.0)

    def test_snapshot_comparison_markdown_is_local_and_descriptive(self):
        history = [
            {"symbol": "SPY", "as_of": "2026-08-12", "score": 60, "action": "Manter/observar"},
            {"symbol": "SPY", "as_of": "2026-08-13", "score": 74, "action": "Considerar compra"},
        ]
        with patch.object(app_server, "load_signal_history", return_value=history):
            filename, content = app_server.snapshot_comparison_markdown()
        self.assertEqual(filename, "radar-comparacao-snapshots.md")
        self.assertIn("Variação média do score", content)
        self.assertIn("SPY", content)

    def test_state_exposes_universe_and_snapshot(self):
        state = app_server.load_state()
        self.assertTrue(state["universe"])
        self.assertTrue(state["signals"])
        self.assertIn("portfolio", state)
        self.assertIn("supervision", state)
        self.assertIn("outcomes", state)
        self.assertIn("network_usage", state)
        self.assertIn("network_plan", state)
        self.assertIn("report_library", state)
        self.assertIn("sensitivity", state)
        self.assertIn("live_validation", state)
        self.assertTrue(state["sensitivity"]["available"])
        self.assertIn("quota", state)
        self.assertIn("automation", state)
        self.assertIn("automation_history", state)
        self.assertIn("artifact_status", state)
        self.assertIn("summary", state["outcomes"])
        self.assertTrue(any("Paper trading" in item["title"] for item in state["supervision"]))
        self.assertIn("sector_exposure", state["portfolio"])
        self.assertIn("risk_contribution", state["portfolio"])

    def test_dashboard_state_omits_heavy_diagnostics_from_transport(self):
        full_state = app_server.load_state()
        dashboard_state = app_server.load_state(include_heavy=False)
        self.assertNotIn("macro_series", dashboard_state["context"])
        self.assertNotIn("rows", dashboard_state["backtest"])
        self.assertLess(len(json.dumps(dashboard_state, ensure_ascii=False)), len(json.dumps(full_state, ensure_ascii=False)))

    def test_state_exposes_paper_status_without_duplicate_no_progress_warning(self):
        state = app_server.load_state()
        self.assertTrue(state["paper"]["paper_only"])
        self.assertGreaterEqual(state["paper"]["review_progress"]["snapshots"], 3)
        coverage = state["paper"]["review_progress"].get("coverage", {})
        self.assertTrue(coverage.get("available"))
        self.assertGreaterEqual(coverage.get("potential_weekdays", 0), coverage.get("observed_snapshots", 0))
        paper_titles = [item["title"] for item in state["supervision"] if "Paper trading" in item["title"]]
        self.assertTrue(any(item["title"] == "Cobertura paper incompleta" for item in state["supervision"]))
        self.assertEqual(paper_titles, ["Paper trading em validação"])

    def test_state_explains_duplicate_paper_review_separately(self):
        state = app_server.load_state()
        review = state["paper"].get("last_entry_review", {})
        if review.get("status") != "duplicate":
            self.skipTest("O snapshot atual nao e uma repeticao da mesma data de mercado.")
        self.assertTrue(any(item["title"] == "Paper sem nova ronda" for item in state["supervision"]))

    def test_paper_report_and_trades_are_local_artifacts(self):
        self.assertTrue(app_server.PAPER_REPORT_PATH.is_file())
        self.assertTrue(app_server.PAPER_TRADES_PATH.is_file())
        report = app_server.PAPER_REPORT_PATH.read_text(encoding="utf-8")
        trades = app_server.PAPER_TRADES_PATH.read_text(encoding="utf-8")
        self.assertIn("Paper trading", report)
        self.assertIn("date,action,symbol", trades)
        self.assertNotIn("API_KEY", report)

    def test_sensitivity_report_is_local_and_exposes_current_grid(self):
        metadata = app_server.sensitivity_report_metadata()
        self.assertTrue(metadata["available"])
        self.assertEqual(metadata["scenario_count"], 108)
        report = app_server.sensitivity_report_path().read_text(encoding="utf-8")
        self.assertIn("**Cenários:** 108", report)
        self.assertIn("Custo bps", report)

    def test_live_validation_report_is_local_and_secret_free(self):
        validation = app_server.live_validation_snapshot()
        self.assertTrue(validation["available"])
        self.assertTrue(validation["passed"])
        filename, report = app_server.live_validation_markdown()
        self.assertEqual(filename, "radar-validacao-live.md")
        self.assertIn("Validação live", report)
        self.assertNotIn("API_KEY", report)

    def test_daily_budget_snapshot_marks_attention_and_exhaustion(self):
        today = dt.datetime.now(dt.timezone.utc).date().isoformat()
        config = {"network": {"daily_call_budgets": {"alpha_vantage": 10, "fred": 5}}}
        stats = {"daily_calls": {"alpha_vantage": {"date": today, "calls": 9}, "fred": {"date": today, "calls": 5}}}
        rows = {item["provider"]: item for item in app_server.daily_budget_snapshot(config, stats)}
        self.assertEqual(rows["alpha_vantage"]["status"], "atencao")
        self.assertEqual(rows["fred"]["status"], "esgotado")

    def test_known_asset_analysis_is_explanatory(self):
        result = app_server.analyze("gold")
        self.assertIsNotNone(result)
        self.assertEqual(result["signal"]["symbol"], "GOLD")
        self.assertIn("note", result)
        self.assertIn("backtest", result)

    def test_catalog_asset_can_export_report_without_api_call(self):
        filename, content = app_server.markdown_report("SPY")
        self.assertEqual(filename, "radar-spy-relatorio.md")
        self.assertIn("# Relatório de SPY", content)
        self.assertIn("Uso responsável", content)
        self.assertIn("Mudanças desde a leitura anterior", content)

    def test_catalog_includes_configured_universe_assets(self):
        symbols = {str(item.get("symbol", "")).upper() for item in app_server.load_catalog()}
        self.assertIn("URANIUM", symbols)

    def test_catalog_asset_can_export_pdf_without_api_call(self):
        filename, content = app_server.pdf_report("SPY")
        self.assertEqual(filename, "radar-spy-relatorio.pdf")
        self.assertTrue(content.startswith(b"%PDF-1.4"))
        self.assertGreater(len(content), 1000)

    def test_daily_report_can_export_pdf_without_api_call(self):
        filename, content = app_server.daily_pdf_report()
        self.assertTrue(filename.startswith("radar-diario-"))
        self.assertTrue(filename.endswith(".pdf"))
        self.assertTrue(content.startswith(b"%PDF-1.4"))
        self.assertGreater(len(content), 1000)

    def test_report_library_lists_local_archive_without_network(self):
        original_output = app_server.OUTPUT_DIR
        try:
            with tempfile.TemporaryDirectory() as temporary:
                app_server.OUTPUT_DIR = Path(temporary)
                reports = app_server.OUTPUT_DIR / "reports"
                reports.mkdir()
                (reports / "radar-diario-2026-08-13.md").write_text("# local", encoding="utf-8")
                entries = app_server.report_library_entries()
                self.assertEqual(entries[0]["as_of"], "2026-08-13")
                self.assertIsNone(entries[0]["pdf"])
        finally:
            app_server.OUTPUT_DIR = original_output

    def test_portfolio_report_is_local_and_contains_risk_sections(self):
        with patch.object(app_server, "load_portfolio_targets", return_value={"Energia": 0.5}):
            filename, content = app_server.portfolio_markdown_report()
        self.assertEqual(filename, "radar-carteira-relatorio.md")
        self.assertIn("# Relatório local da carteira", content)
        self.assertIn("## Exposição por setor", content)
        self.assertIn("## Contribuição para variabilidade", content)
        self.assertIn("## Quota e qualidade", content)
        self.assertIn("Chamadas externas efetivamente tentadas", content)
        self.assertIn("Foco: carteira e setores em destaque", content)
        self.assertIn("score medio >= 80/100", content)
        self.assertIn("Nenhum setor atingiu 80/100", content)
        self.assertIn("## Desvio face às metas", content)
        self.assertIn("Ajuste indicativo", content)
        self.assertIn("## Cobertura de monitorização", content)
        self.assertIn("Próxima prioridade local", content)
        self.assertIn("não atualiza providers nem cria ordens", content)
        self.assertNotIn("ALPHAVANTAGE_API_KEY", content)

    def test_portfolio_pdf_is_local_and_focused_on_threshold(self):
        filename, content = app_server.portfolio_pdf_report()
        self.assertTrue(filename.startswith("radar-carteira-"))
        self.assertTrue(content.startswith(b"%PDF-1.4"))
        self.assertNotIn(b"ALPHAVANTAGE_API_KEY", content)

    def test_asset_reports_include_historical_outcomes_when_available(self):
        _, markdown = app_server.markdown_report("BTC")
        self.assertIn("Evidência histórica deste ativo", markdown)
        _, pdf = app_server.pdf_report("BTC")
        self.assertIn(b"EVIDENCIA HISTORICA", pdf)

    def test_asset_pdf_includes_recent_changes_when_available(self):
        state = app_server.load_state()
        state["alerts"] = [{
            "symbol": "URANIUM",
            "type": "SCORE_MOVE",
            "from_action": "Não agir",
            "to_action": "Manter/observar",
            "score_delta": 12.0,
            "dominant_factor": "momentum",
            "dominant_factor_delta": 12.0,
            "reason": "a pontuação mudou pelo menos 10 pontos",
        }]
        with patch.object(app_server, "load_state", return_value=state):
            _, pdf = app_server.pdf_report("URANIUM")
        self.assertIn(b"HISTORICO RECENTE", pdf)

    def test_local_journal_is_attached_to_snapshot_and_reports(self):
        original = app_server.JOURNAL_PATH
        try:
            with tempfile.TemporaryDirectory() as temporary:
                app_server.JOURNAL_PATH = Path(temporary) / "decision_journal.json"
                as_of = str(app_server.load_state()["meta"]["as_of"])
                app_server.save_journal_entry("SPY", as_of, "Confirmar volume antes de alterar a posição.")
                state = app_server.load_state()
                self.assertTrue(any(item["symbol"] == "SPY" for item in state["journal"]))
                _, markdown = app_server.markdown_report("SPY")
                self.assertIn("Nota pessoal", markdown)
                self.assertIn("Confirmar volume", markdown)
                _, pdf = app_server.pdf_report("SPY")
                self.assertIn(b"NOTA PESSOAL", pdf)
        finally:
            app_server.JOURNAL_PATH = original

    def test_live_request_reuses_fresh_on_demand_cache(self):
        original = app_server.ON_DEMAND_DIR
        try:
            with tempfile.TemporaryDirectory() as temporary:
                app_server.ON_DEMAND_DIR = Path(temporary)
                app_server.write_json(app_server.ON_DEMAND_DIR / "spy.json", {
                    "ok": True,
                    "signal": {"symbol": "SPY", "price": 500},
                    "quality": {"symbol": "SPY", "status": "OK"},
                    "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                })
                result = app_server.collect_live_analysis("SPY")
                self.assertTrue(result["cached"])
                self.assertEqual(result["usage"]["mode"], "cache")
                self.assertEqual(result["usage_details"]["provider"], "alpha_vantage")
                self.assertGreater(result["usage_details"]["ttl_seconds"], 0)
        finally:
            app_server.ON_DEMAND_DIR = original

    def test_state_persists_safe_on_demand_usage_details(self):
        original_cache = app_server.ON_DEMAND_DIR
        original_output = app_server.OUTPUT_DIR
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                app_server.ON_DEMAND_DIR = root / "on_demand"
                app_server.OUTPUT_DIR = root / "outputs"
                app_server.OUTPUT_DIR.mkdir()
                app_server.write_json(app_server.ON_DEMAND_DIR / "spy.json", {
                    "signal": {"symbol": "SPY", "price": 500},
                    "quality": {"symbol": "SPY", "status": "OK"},
                    "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "usage_details": {"provider": "alpha_vantage", "ttl_seconds": 21600, "context_reused": True, "url": "must-not-leak"},
                })
                state = app_server.load_state()
                usage = next(item for item in state["on_demand"] if item["symbol"] == "SPY")["usage_details"]
                self.assertEqual(usage["provider"], "alpha_vantage")
                self.assertNotIn("url", usage)
        finally:
            app_server.ON_DEMAND_DIR = original_cache
            app_server.OUTPUT_DIR = original_output

    def test_live_plan_reports_cache_and_key_requirements_without_network(self):
        original_cache = app_server.ON_DEMAND_DIR
        original_output = app_server.OUTPUT_DIR
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                app_server.ON_DEMAND_DIR = root / "on_demand"
                app_server.OUTPUT_DIR = root / "outputs"
                app_server.OUTPUT_DIR.mkdir()
                app_server.write_json(app_server.OUTPUT_DIR / "momentum_data.json", {
                    "meta": {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "context_available": True},
                    "context": {"news_available": True, "macro_available": True},
                })
                with patch.dict(os.environ, {"ALPHAVANTAGE_API_KEY": "", "FRED_API_KEY": ""}):
                    plan = app_server.live_analysis_plan("SPY")
                self.assertTrue(plan["ok"])
                self.assertEqual(plan["cache"]["status"], "missing_or_stale")
                self.assertEqual(plan["context"]["status"], "reused")
                self.assertGreater(plan["estimated_calls"], 0)
                self.assertIn("ALPHAVANTAGE_API_KEY", plan["missing_keys"])
                self.assertFalse(plan["provider_cooldown"]["active"])
                self.assertEqual(plan["provider_cooldowns"], [])
        finally:
            app_server.ON_DEMAND_DIR = original_cache
            app_server.OUTPUT_DIR = original_output

    def test_live_plan_counts_each_macro_series_as_a_call(self):
        original_cache = app_server.ON_DEMAND_DIR
        original_output = app_server.OUTPUT_DIR
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                app_server.ON_DEMAND_DIR = root / "on_demand"
                app_server.OUTPUT_DIR = root / "outputs"
                app_server.OUTPUT_DIR.mkdir()
                with patch.dict(os.environ, {"ALPHAVANTAGE_API_KEY": "", "FRED_API_KEY": ""}):
                    plan = app_server.live_analysis_plan("SPY")
                self.assertEqual(plan["context"]["status"], "will_refresh")
                self.assertEqual(plan["estimated_calls"], 9)
                self.assertEqual(sum(str(item["resource"]).startswith("macro ") for item in plan["calls"]), 5)
        finally:
            app_server.ON_DEMAND_DIR = original_cache
            app_server.OUTPUT_DIR = original_output

    def test_daily_budget_reports_shortfall_before_network(self):
        today = dt.datetime.now(dt.timezone.utc).date().isoformat()
        rows = app_server.daily_budget_rows(
            {"network": {"daily_call_budgets": {"alpha_vantage": 2}}},
            {"daily_calls": {"alpha_vantage": {"date": today, "calls": 1}}},
            [{"provider": "alpha_vantage", "resource": "asset"}, {"provider": "news", "resource": "news"}],
        )
        self.assertEqual(rows[0]["provider"], "alpha_vantage")
        self.assertEqual(rows[0]["remaining"], 1)
        self.assertEqual(rows[0]["shortfall"], 1)

    def test_live_error_redacts_configured_secret(self):
        import os

        previous = os.environ.get("ALPHAVANTAGE_API_KEY")
        try:
            os.environ["ALPHAVANTAGE_API_KEY"] = "secret-key-123456"
            message = app_server.safe_error_message("provider rejected secret-key-123456")
            self.assertNotIn("secret-key-123456", message)
            self.assertIn("<redacted>", message)
        finally:
            if previous is None:
                os.environ.pop("ALPHAVANTAGE_API_KEY", None)
            else:
                os.environ["ALPHAVANTAGE_API_KEY"] = previous

    def test_portfolio_file_is_kept_separate_from_project_outputs(self):
        original = app_server.PORTFOLIO_PATH
        try:
            with tempfile.TemporaryDirectory() as temporary:
                app_server.PORTFOLIO_PATH = Path(temporary) / "portfolio.json"
                app_server.write_json(app_server.PORTFOLIO_PATH, {
                    "updated_at": "2026-08-06T00:00:00+00:00",
                    "positions": [{"symbol": "GLD", "quantity": 2, "avg_cost": 180, "currency": "USD"}],
                })
                state = app_server.load_state()
                self.assertEqual(state["portfolio"]["positions"][0]["symbol"], "GLD")
                self.assertTrue(app_server.PORTFOLIO_PATH.exists())
        finally:
            app_server.PORTFOLIO_PATH = original


if __name__ == "__main__":
    unittest.main()
