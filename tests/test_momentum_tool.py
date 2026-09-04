import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import momentum_tool  # noqa: E402


class MomentumToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = momentum_tool.load_config(Path(__file__).resolve().parents[1] / "config.json")

    def test_demo_is_deterministic_and_has_global_benchmark(self):
        first = momentum_tool.generate_demo_data(self.config)
        second = momentum_tool.generate_demo_data(self.config)
        self.assertEqual(first, second)
        self.assertIn("GLOBAL", {row["symbol"] for row in first})

    def test_weekend_full_live_run_is_skipped_but_explicit_symbols_are_allowed(self):
        saturday = dt.date(2026, 8, 22)
        config = {"network": {"skip_weekend_full_runs": True}}
        self.assertTrue(momentum_tool.should_skip_weekend_run(config, "live", set(), saturday))
        self.assertFalse(momentum_tool.should_skip_weekend_run(config, "live", {"BTC"}, saturday))
        self.assertFalse(momentum_tool.should_skip_weekend_run(config, "demo", set(), saturday))

    def test_expanded_universe_profile_adds_price_only_coverage(self):
        config = json.loads(json.dumps(self.config))
        momentum_tool.apply_universe_profile(config, "expanded")
        symbols = {item["symbol"] for item in config["universe"]}
        self.assertIn("CLOU", symbols)
        self.assertIn("KRE", symbols)
        self.assertGreater(len(symbols), len(self.config["universe"]))
        self.assertEqual(len(symbols), len(config["universe"]))
        self.assertEqual(config["universe_profile"], "expanded")

    def test_portfolio_monitor_selects_largest_positions_and_marks_them(self):
        config = json.loads(json.dumps(self.config))
        selected, plan = momentum_tool.prepare_portfolio_monitor(config, limit=3, snapshot_path=Path("missing-portfolio-snapshot.json"))
        self.assertEqual(len(selected), 3)
        self.assertEqual(plan["selected_symbols"], sorted(selected))
        monitored = [item for item in config["universe"] if item.get("portfolio_monitor_only")]
        self.assertEqual({item["symbol"] for item in monitored}, selected)

    def test_portfolio_monitor_prioritizes_unread_then_oldest(self):
        config = json.loads(json.dumps(self.config))
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "user_portfolio.json").write_text(json.dumps({"positions": [
                {"symbol": "AAA", "statement_value_eur": 9000},
                {"symbol": "BBB", "statement_value_eur": 1000},
                {"symbol": "CCC", "statement_value_eur": 500},
            ]}), encoding="utf-8")
            (data_dir / "portfolio_import_2026-08-06.json").write_text(json.dumps({"assets": [
                {"symbol": "AAA", "sector": "Teste", "provider": "yahoo_finance", "source_id": "AAA"},
                {"symbol": "BBB", "sector": "Teste", "provider": "yahoo_finance", "source_id": "BBB"},
                {"symbol": "CCC", "sector": "Teste", "provider": "yahoo_finance", "source_id": "CCC"},
            ]}), encoding="utf-8")
            snapshot_path = data_dir / "momentum_data.json"
            snapshot_path.write_text(json.dumps({
                "meta": {"as_of": "2026-08-14"},
                "signals": [{"symbol": "AAA"}],
                "history": [{"symbol": "BBB", "date": "2026-08-10"}],
            }), encoding="utf-8")
            with patch.object(momentum_tool, "DATA_DIR", data_dir):
                selected, plan = momentum_tool.prepare_portfolio_monitor(config, limit=2, snapshot_path=snapshot_path)
        self.assertEqual(selected, {"BBB", "CCC"})
        self.assertNotIn("AAA", selected)
        self.assertEqual(plan["selection"], "sem leitura primeiro; depois leitura mais antiga; valor como desempate")

    def test_portfolio_monitor_is_trimmed_to_preserve_daily_reserve(self):
        monitor = {"selected_symbols": ["AAA", "BBB"], "reserve_calls": 5}
        def fake_plan(_config, active):
            shortfall = 1 if "BBB" in active else 0
            return {"network_allowed": not shortfall, "daily_budgets": [{"provider": "fixture", "shortfall": shortfall}]}
        with patch.object(momentum_tool, "live_network_plan", side_effect=fake_plan):
            active, adjusted, plan = momentum_tool.fit_portfolio_monitor_to_budget({}, {"CORE", "AAA", "BBB"}, monitor)
        self.assertEqual(active, {"CORE", "AAA"})
        self.assertEqual(adjusted["selected_symbols"], ["AAA"])
        self.assertEqual(adjusted["trimmed_symbols"], ["BBB"])
        self.assertTrue(adjusted["budget_fitted"])
        self.assertTrue(plan["network_allowed"])

    def test_expanded_profile_rotates_balanced_cohort_and_keeps_core(self):
        config = json.loads(json.dumps(self.config))
        momentum_tool.apply_universe_profile(config, "expanded")
        active_zero, plan_zero = momentum_tool.select_rotating_cohort(config, "expanded", cohort_size=15, cohort_index=0)
        active_one, plan_one = momentum_tool.select_rotating_cohort(config, "expanded", cohort_size=15, cohort_index=1)
        core_config = json.loads(json.dumps(self.config))
        core_symbols = {item["symbol"] for item in core_config["universe"]}
        self.assertTrue(core_symbols.issubset(active_zero))
        self.assertLessEqual(len(plan_zero["selected_additions"]), 15)
        self.assertTrue(plan_zero["sector_coverage"])
        self.assertEqual(plan_zero["next_index"], 1)
        self.assertIsNone(plan_zero["next_rotation_date"])
        self.assertNotEqual(set(plan_zero["selected_additions"]), set(plan_one["selected_additions"]))
        self.assertNotEqual(active_zero, active_one)

    def test_decision_round_explains_buy_gate_and_near_entries(self):
        signals = [
            {"symbol": "CLOUD", "action": "Manter/observar", "score": 60.0, "data_points": 900},
            {"symbol": "BANKS", "action": "Manter/observar", "score": 55.5, "data_points": 900},
            {"symbol": "SHORT", "action": "Considerar compra", "score": 82.0, "data_points": 900},
        ]
        result = momentum_tool.summarize_decision_round(signals, {"buy_score": 80})
        self.assertEqual(result["status"], "para investigar")
        self.assertEqual(result["buy_candidates"], ["SHORT"])
        self.assertEqual([item["symbol"] for item in result["near_entry_candidates"]], ["CLOUD", "BANKS"])
        self.assertEqual(result["near_entry_candidates"][0]["gap_to_buy"], 20.0)
        self.assertTrue(result["near_entry_candidates"][0]["watch_factors"])

    def test_alerts_detect_action_transition_and_score_move(self):
        previous = {"meta": {"mode": "live", "as_of": "2026-08-04"}, "signals": [{"symbol": "AI", "action": "Manter/observar", "score": 54.0, "confidence": 90.0, "momentum": 48.0}]}
        current = {"meta": {"mode": "live", "as_of": "2026-08-05"}, "signals": [{"symbol": "AI", "action": "Considerar compra", "score": 82.0, "confidence": 91.0, "momentum": 76.0}]}
        alerts = momentum_tool.build_alerts(previous, current)
        self.assertTrue(alerts["comparable"])
        self.assertEqual(alerts["events"][0]["type"], "ACTION_CHANGE")
        self.assertEqual(alerts["events"][0]["score_delta"], 28.0)
        self.assertIn("momentum", alerts["events"][0]["reason"])
        self.assertEqual(alerts["events"][0]["dominant_factor"], "momentum")
        self.assertEqual(alerts["events"][0]["dominant_factor_direction"], "subiu")

    def test_backtest_exposes_execution_assumptions(self):
        rows = momentum_tool.generate_demo_data(self.config)
        result = momentum_tool.backtest(rows, self.config)
        self.assertEqual(result["assumptions"]["signal_delay_days"], 1)
        self.assertEqual(result["assumptions"]["slippage_bps"], 5.0)
        self.assertIn("turnover", result["strategy"])
        self.assertTrue(all("turnover" in row for row in result["rows"]))

    def test_walk_forward_returns_separate_test_folds(self):
        rows = momentum_tool.generate_demo_data(self.config)
        result = momentum_tool.walk_forward_backtest(rows, self.config)
        self.assertIn(result["status"], {"ok", "amostra insuficiente", "sem dados"})
        if result["folds"]:
            self.assertIn("test_start", result["folds"][0])
            self.assertIn("strategy", result["folds"][0])

    def test_validate_config_catches_invalid_crypto_and_duplicate_symbol(self):
        invalid = json.loads(json.dumps(self.config))
        invalid["universe"].append({"symbol": "BTC", "sector": "Cripto", "provider": "coinmarketcap", "source_id": "btc"})
        result = momentum_tool.validate_config(invalid)
        self.assertTrue(any("símbolo duplicado" in error for error in result["errors"]))
        self.assertTrue(any("source_id numérico" in error for error in result["errors"]))

    def test_signal_outcomes_are_recorded_once_when_horizon_is_available(self):
        dates = momentum_tool.business_dates(30, dt.date(2026, 8, 5))
        rows = [{"date": date.isoformat(), "symbol": "AI", "sector": "IA", "close": 100.0 + index, "volume": 1000.0, "currency": "USD", "source": "fixture", "source_id": "AI"} for index, date in enumerate(dates)]
        with tempfile.TemporaryDirectory() as output_dir:
            history_path = Path(output_dir) / "signal-history.jsonl"
            outcomes_path = Path(output_dir) / "signal-outcomes.jsonl"
            history_path.write_text(json.dumps({"as_of": dates[0].isoformat(), "mode": "demo", "symbol": "AI", "sector": "IA", "price": 100.0, "action": "Manter/observar", "score": 60.0, "confidence": 90.0}) + "\n", encoding="utf-8")
            created = momentum_tool.append_signal_outcomes(history_path, outcomes_path, rows, [5, 20])
            self.assertEqual(created, 2)
            self.assertEqual(momentum_tool.append_signal_outcomes(history_path, outcomes_path, rows, [5, 20]), 0)
            outcomes = [json.loads(line) for line in outcomes_path.read_text(encoding="utf-8").splitlines()]
            self.assertAlmostEqual(outcomes[0]["forward_return"], 0.05, places=5)

    def test_quality_marks_missing_benchmark_and_stale_data(self):
        stale = (dt.date.today() - dt.timedelta(days=10)).isoformat()
        rows = [{
            "date": stale,
            "symbol": "AI",
            "sector": "IA e semicondutores",
            "close": 100.0,
            "volume": 1000.0,
            "currency": "USD",
            "source": "fixture",
            "source_id": "AI",
        }]
        quality = momentum_tool.quality_rows(rows, self.config, [])
        by_symbol = {row["symbol"]: row for row in quality}
        self.assertEqual(by_symbol["AI"]["status"], "ATRASADO")
        self.assertEqual(by_symbol["GLOBAL"]["status"], "ERRO")

    def test_quality_marks_duplicates_gaps_and_invalid_prices(self):
        today = dt.date.today()
        rows = [
            {"date": (today - dt.timedelta(days=20)).isoformat(), "symbol": "AI", "sector": "IA", "close": 100.0, "volume": 1000.0, "source": "fixture"},
            {"date": (today - dt.timedelta(days=20)).isoformat(), "symbol": "AI", "sector": "IA", "close": 0.0, "volume": 1000.0, "source": "fixture"},
            {"date": (today - dt.timedelta(days=1)).isoformat(), "symbol": "AI", "sector": "IA", "close": 101.0, "volume": 1000.0, "source": "fixture"},
        ]
        quality = momentum_tool.quality_rows(rows, self.config, [])
        ai = next(row for row in quality if row["symbol"] == "AI")
        self.assertEqual(ai["status"], "ERRO")
        self.assertEqual(ai["duplicate_dates"], 1)
        self.assertEqual(ai["gap_count"], 1)
        self.assertEqual(ai["invalid_prices"], 1)
        self.assertIn("duplicada", ai["message"])
        self.assertIn("lacuna", ai["message"])
        self.assertIn("inválido", ai["message"])

    def test_backtest_without_benchmark_returns_empty_safe_result(self):
        rows = [{
            "date": dt.date.today().isoformat(),
            "symbol": "AI",
            "sector": "IA e semicondutores",
            "close": 100.0,
            "volume": 1000.0,
            "currency": "USD",
            "source": "fixture",
            "source_id": "AI",
        }]
        result = momentum_tool.backtest(rows, self.config)
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["strategy"]["observations"], 0)

    def test_live_signals_are_blocked_without_benchmark(self):
        signals = [{"action": "Considerar compra", "notes": "confirmação"}]
        guarded = momentum_tool.guard_signals(signals, "live", False)
        self.assertEqual(guarded[0]["action"], "Não agir")
        self.assertIn("bloqueada", guarded[0]["notes"])

    def test_live_signals_are_blocked_without_context(self):
        signals = [{"action": "Considerar compra", "notes": "confirmação"}]
        guarded = momentum_tool.guard_signals(signals, "live", True, False)
        self.assertEqual(guarded[0]["action"], "Não agir")
        self.assertIn("notícias/ambiente económico", guarded[0]["notes"].lower())

    def test_live_fixture_without_benchmark_writes_report(self):
        row = {
            "date": dt.date.today().isoformat(),
            "symbol": "AI",
            "sector": "IA e semicondutores",
            "close": 100.0,
            "volume": 1000.0,
            "currency": "USD",
            "source": "fixture",
            "source_id": "AI",
        }
        provider_quality = [{
            "symbol": "AI",
            "source": "yahoo_finance",
            "rows": 1,
            "status": "OK",
            "message": "fallback alpha_vantage -> yahoo_finance",
            "provider_requested": "alpha_vantage",
            "provider_used": "yahoo_finance",
            "fallback_used": True,
        }]
        context = {"news_scores": {"AI": 67.0}, "macro_score": 61.0, "macro_series": {}, "news_available": True, "macro_available": True}
        with tempfile.TemporaryDirectory() as output_dir:
            with patch.object(momentum_tool, "fetch_live_data", return_value=([row], provider_quality, context)):
                with patch.object(momentum_tool.sys, "argv", ["momentum_tool.py", "--mode", "live", "--output-dir", output_dir]):
                    momentum_tool.main()
            payload = json.loads((Path(output_dir) / "momentum_data.json").read_text(encoding="utf-8"))
            self.assertFalse(payload["meta"]["benchmark_available"])
            self.assertEqual(payload["signals"][0]["action"], "Não agir")
            self.assertEqual(payload["signals"][0]["news"], 67.0)
            self.assertEqual(payload["signals"][0]["macro"], 61.0)
            self.assertEqual(payload["history"][0]["symbol"], "AI")
            report = (Path(output_dir) / "relatorio-momentum.md").read_text(encoding="utf-8")
            self.assertIn("Guia de leitura", report)
            self.assertIn("Alertas desde a última execução", report)
            self.assertIn("Pulso por setor", report)
            self.assertIn("Orçamento diário local", report)
            self.assertIn("Chamadas externas efetivamente tentadas", report)
            self.assertIn("CAGR", report)
            self.assertIn("Fallback de provider", report)
            self.assertIn("alpha_vantage -> yahoo_finance", report)
            self.assertIn("Não é a probabilidade de lucro", report)
            self.assertTrue((Path(output_dir) / "reports" / f"radar-diario-{row['date']}.md").is_file())
            self.assertTrue((Path(output_dir) / "reports" / f"radar-diario-{row['date']}.pdf").is_file())

    def test_report_failure_keeps_core_snapshot_available(self):
        row = {
            "date": dt.date.today().isoformat(),
            "symbol": "AI",
            "sector": "IA e semicondutores",
            "close": 100.0,
            "volume": 1000.0,
            "currency": "USD",
            "source": "fixture",
            "source_id": "AI",
        }
        provider_quality = [{"symbol": "AI", "source": "fixture", "rows": 1, "status": "OK", "message": ""}]
        context = {"news_scores": {"AI": 67.0}, "macro_score": 61.0, "macro_series": {}, "news_available": True, "macro_available": True}
        with tempfile.TemporaryDirectory() as output_dir:
            with patch.object(momentum_tool, "fetch_live_data", return_value=([row], provider_quality, context)):
                with patch.object(momentum_tool, "write_report", side_effect=RuntimeError("layout inválido")):
                    with patch.object(momentum_tool.sys, "argv", ["momentum_tool.py", "--mode", "live", "--output-dir", output_dir]):
                        result = momentum_tool.main()
            payload = json.loads((Path(output_dir) / "momentum_data.json").read_text(encoding="utf-8"))
            self.assertEqual(result, 0)
            self.assertEqual(payload["artifact_status"]["core"], "completed")
            self.assertEqual(payload["artifact_status"]["report"], "failed")
            self.assertEqual(payload["artifact_status"]["error"], "layout inválido")
            self.assertTrue((Path(output_dir) / "signals.csv").is_file())

    def test_expanded_report_explains_cohort_coverage(self):
        row = {
            "date": dt.date.today().isoformat(),
            "symbol": "AI",
            "sector": "IA e semicondutores",
            "close": 100.0,
            "volume": 1000.0,
            "currency": "USD",
            "source": "fixture",
            "source_id": "AI",
        }
        provider_quality = [{"symbol": "AI", "source": "fixture", "rows": 1, "status": "OK", "message": ""}]
        context = {"news_scores": {"AI": 67.0}, "macro_score": 61.0, "macro_series": {}, "news_available": True, "macro_available": True}
        with tempfile.TemporaryDirectory() as output_dir:
            with patch.object(momentum_tool, "fetch_live_data", return_value=([row], provider_quality, context)):
                with patch.object(momentum_tool.sys, "argv", ["momentum_tool.py", "--mode", "live", "--universe-profile", "expanded", "--cohort-size", "1", "--cohort-index", "0", "--output-dir", output_dir]):
                    momentum_tool.main()
            report = (Path(output_dir) / "relatorio-momentum.md").read_text(encoding="utf-8")
            self.assertIn("Cobertura desta ronda", report)
            self.assertIn("fora da coorte", report)
            self.assertIn("Proxima coorte automatica", report)

    def test_report_handles_manual_coverage_without_next_rotation(self):
        row = {
            "date": dt.date.today().isoformat(),
            "symbol": "AI",
            "sector": "IA e semicondutores",
            "close": 100.0,
            "volume": 1000.0,
            "currency": "USD",
            "source": "fixture",
            "source_id": "AI",
        }
        provider_quality = [{"symbol": "AI", "source": "fixture", "rows": 1, "status": "OK", "message": ""}]
        context = {"news_scores": {"AI": 67.0}, "macro_score": 61.0, "macro_series": {}, "news_available": True, "macro_available": True}
        with tempfile.TemporaryDirectory() as output_dir:
            with patch.object(momentum_tool, "fetch_live_data", return_value=([row], provider_quality, context)):
                with patch.object(momentum_tool.sys, "argv", ["momentum_tool.py", "--mode", "live", "--output-dir", output_dir]):
                    momentum_tool.main()
            payload_path = Path(output_dir) / "momentum_data.json"
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            payload["meta"]["cohort"] = {
                "profile": "core",
                "rotation_index": 0,
                "rotation_rounds": None,
                "active_symbols": ["AI"],
                "stale_symbols": [],
                "sector_coverage": ["IA e semicondutores"],
                "rotated": True,
                "automatic": False,
                "next_rotation_index": None,
                "next_rotation_date": None,
            }
            report_path = Path(output_dir) / "manual-coverage.md"
            momentum_tool.write_report(payload, report_path)
            report = report_path.read_text(encoding="utf-8")
            self.assertIn("Proxima coorte automatica: nao agendada", report)

    def test_news_sentiment_maps_tickers_to_symbols(self):
        payload = {
            "feed": [{
                "time_published": "20260801T120000",
                "ticker_sentiment": [{"ticker": "SOXX", "ticker_sentiment_score": "0.7", "relevance_score": "0.9"}],
            }]
        }
        with patch.object(momentum_tool, "cached_http_json", return_value=payload) as requests:
            scores, quality = momentum_tool.fetch_news_sentiment(self.config, "fixture-key")
        self.assertGreater(scores["AI"], 80.0)
        self.assertEqual(quality["status"], "OK")
        self.assertEqual(requests.call_count, 2)

    def test_http_json_retries_provider_rate_limit_envelope(self):
        responses = [
            {"Note": "Please spread out your API requests more sparingly."},
            {"Information": "Rate limit reached; retry later."},
            {"Time Series (Daily)": {"2026-08-05": {"4. close": "100", "5. volume": "10"}}},
        ]

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(self.payload).encode("utf-8")

        original_data_dir = momentum_tool.DATA_DIR
        try:
            with tempfile.TemporaryDirectory() as temporary:
                momentum_tool.DATA_DIR = Path(temporary)
                with patch.object(momentum_tool.urllib.request, "urlopen", side_effect=[FakeResponse(item) for item in responses]):
                    with patch.object(momentum_tool, "_wait_for_rate_limit"):
                        with patch.object(momentum_tool.time, "sleep") as sleep:
                            payload = momentum_tool.http_json("https://example.test", config=self.config, namespace="alpha_vantage")
        finally:
            momentum_tool.DATA_DIR = original_data_dir
        self.assertIn("Time Series (Daily)", payload)
        self.assertEqual(sleep.call_count, 2)

    def test_http_json_does_not_return_provider_rate_limit_envelope(self):
        response = {"Note": "Please spread out your API requests more sparingly."}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(response).encode("utf-8")

        original_data_dir = momentum_tool.DATA_DIR
        try:
            with tempfile.TemporaryDirectory() as temporary:
                momentum_tool.DATA_DIR = Path(temporary)
                with patch.object(momentum_tool.urllib.request, "urlopen", return_value=FakeResponse()):
                    with patch.object(momentum_tool, "_wait_for_rate_limit"):
                        with patch.object(momentum_tool.time, "sleep"):
                            with self.assertRaisesRegex(RuntimeError, "provider rate limit"):
                                momentum_tool.http_json("https://example.test", config=self.config, namespace="alpha_vantage")
        finally:
            momentum_tool.DATA_DIR = original_data_dir

    def test_cache_key_does_not_change_when_api_key_rotates(self):
        first = momentum_tool._cache_key_url("https://example.test/query?apikey=old-key&symbol=SPY")
        second = momentum_tool._cache_key_url("https://example.test/query?apikey=new-key&symbol=SPY")
        self.assertEqual(first, second)

    def test_cache_ttl_can_be_provider_specific(self):
        config = {"cache": {"ttl_seconds": 60, "ttl_by_namespace": {"fred": 86400}}}
        self.assertEqual(momentum_tool._cache_ttl(config, "fred"), 86400)
        self.assertEqual(momentum_tool._cache_ttl(config, "alpha_vantage"), 60)

    def test_cache_stats_store_counters_without_request_details(self):
        original_data_dir = momentum_tool.DATA_DIR
        try:
            with tempfile.TemporaryDirectory() as temporary:
                momentum_tool.DATA_DIR = Path(temporary)
                momentum_tool._record_cache_event("alpha_vantage", "hit")
                momentum_tool._record_cache_event("alpha_vantage", "miss")
                momentum_tool._record_cache_event("alpha_vantage", "error")
                stats = momentum_tool.read_cache_stats()
                self.assertEqual(stats["namespaces"]["alpha_vantage"]["hits"], 1)
                self.assertEqual(stats["namespaces"]["alpha_vantage"]["misses"], 1)
                self.assertEqual(stats["namespaces"]["alpha_vantage"]["errors"], 1)
                self.assertNotIn("url", json.dumps(stats).lower())
        finally:
            momentum_tool.DATA_DIR = original_data_dir

    def test_cache_stats_process_lock_preserves_concurrent_updates(self):
        source_dir = Path(__file__).resolve().parents[1] / "src"
        child = """
import os, sys
from pathlib import Path
sys.path.insert(0, {source_dir!r})
import momentum_tool
momentum_tool.DATA_DIR = Path(os.environ['RADAR_TEST_DATA_DIR'])
for _ in range(20):
    momentum_tool._record_cache_event('test_namespace', 'hit')
    momentum_tool._reserve_provider_call('test_namespace', {{'network': {{}}}})
""".format(source_dir=str(source_dir))
        with tempfile.TemporaryDirectory() as temporary:
            env = os.environ.copy()
            env["RADAR_TEST_DATA_DIR"] = temporary
            processes = [subprocess.Popen([sys.executable, "-c", child], cwd=str(source_dir.parent), env=env) for _ in range(2)]
            exit_codes = [process.wait() for process in processes]
            stats = json.loads((Path(temporary) / "cache" / "stats.json").read_text(encoding="utf-8"))
        self.assertEqual(exit_codes, [0, 0])
        self.assertEqual(stats["namespaces"]["test_namespace"]["hits"], 40)
        self.assertEqual(stats["daily_calls"]["test_namespace"]["calls"], 40)

    def test_outbound_calls_are_recorded_without_a_configured_budget(self):
        original_data_dir = momentum_tool.DATA_DIR
        try:
            with tempfile.TemporaryDirectory() as temporary:
                momentum_tool.DATA_DIR = Path(temporary)
                config = {"network": {}}

                class FakeResponse:
                    def __enter__(self):
                        return self

                    def __exit__(self, *_args):
                        return False

                    def read(self):
                        return json.dumps({"ok": True}).encode("utf-8")

                with patch.object(momentum_tool.urllib.request, "urlopen", return_value=FakeResponse()):
                    self.assertEqual(momentum_tool.http_json("https://example.test", config=config, namespace="alpha_vantage"), {"ok": True})
                stats = momentum_tool.read_cache_stats()
                self.assertEqual(stats["daily_calls"]["alpha_vantage"]["calls"], 1)
        finally:
            momentum_tool.DATA_DIR = original_data_dir

    def test_cache_stats_delta_reports_outbound_calls_and_cache_events(self):
        before = {"namespaces": {"alpha_vantage": {"hits": 2, "misses": 3}}, "daily_calls": {"alpha_vantage": {"date": "2026-08-13", "calls": 4}}}
        after = {"namespaces": {"alpha_vantage": {"hits": 4, "misses": 4, "errors": 1}}, "daily_calls": {"alpha_vantage": {"date": "2026-08-13", "calls": 6}}}
        delta = momentum_tool.cache_stats_delta(before, after, dt.datetime(2026, 8, 13, tzinfo=dt.timezone.utc))
        self.assertEqual(delta["outbound_calls"], 2)
        self.assertEqual(delta["outbound_calls_by_bucket"]["alpha_vantage"], 2)
        self.assertEqual(delta["cache_events"]["alpha_vantage"]["hits"], 2)
        self.assertEqual(delta["cache_events"]["alpha_vantage"]["errors"], 1)

    def test_stale_cache_is_explicitly_used_after_provider_failure(self):
        original_data_dir = momentum_tool.DATA_DIR
        try:
            with tempfile.TemporaryDirectory() as temporary:
                momentum_tool.DATA_DIR = Path(temporary)
                config = {"cache": {"enabled": True, "ttl_seconds": 0, "stale_if_error": True}}
                url = "https://example.test/query?symbol=SPY"
                cache_root = momentum_tool.DATA_DIR / "cache" / "alpha_vantage"
                cache_root.mkdir(parents=True)
                cache_file = cache_root / f"{momentum_tool.hashlib.sha256(momentum_tool._cache_key_url(url).encode('utf-8')).hexdigest()}.json"
                cache_file.write_text(json.dumps({"Time Series (Daily)": {"2026-08-12": {"4. close": "100"}}}), encoding="utf-8")
                old_time = dt.datetime.now().timestamp() - 3600
                os.utime(cache_file, (old_time, old_time))
                with patch.object(momentum_tool, "http_json", side_effect=RuntimeError("provider offline")):
                    payload = momentum_tool.cached_http_json(url, config, "alpha_vantage")
                self.assertEqual(payload["_radar_cache"]["status"], "stale_fallback")
                stats = momentum_tool.read_cache_stats()
                self.assertEqual(stats["namespaces"]["alpha_vantage"]["stale_fallbacks"], 1)
        finally:
            momentum_tool.DATA_DIR = original_data_dir

    def test_provider_cooldown_blocks_repeated_network_attempts(self):
        original_data_dir = momentum_tool.DATA_DIR
        try:
            with tempfile.TemporaryDirectory() as temporary:
                momentum_tool.DATA_DIR = Path(temporary)
                config = {"network": {"provider_cooldown_seconds": 60}}
                momentum_tool._record_provider_cooldown("alpha_vantage", config)
                with patch.object(momentum_tool.urllib.request, "urlopen") as urlopen:
                    with self.assertRaisesRegex(RuntimeError, "cooldown local"):
                        momentum_tool.http_json("https://example.test", config=config, namespace="alpha_vantage")
                urlopen.assert_not_called()
                stats = momentum_tool.read_cache_stats()
                self.assertEqual(stats["cooldowns"]["alpha_vantage"]["reason"], "rate_limit")
        finally:
            momentum_tool.DATA_DIR = original_data_dir

    def test_news_and_price_share_alpha_vantage_cooldown_bucket(self):
        original_data_dir = momentum_tool.DATA_DIR
        try:
            with tempfile.TemporaryDirectory() as temporary:
                momentum_tool.DATA_DIR = Path(temporary)
                config = {"network": {"provider_cooldown_seconds": 60}}
                momentum_tool._record_provider_cooldown("news", config)
                with self.assertRaisesRegex(RuntimeError, "cooldown local"):
                    momentum_tool.http_json("https://example.test", config=config, namespace="alpha_vantage")
        finally:
            momentum_tool.DATA_DIR = original_data_dir

    def test_daily_provider_budget_blocks_before_network(self):
        original_data_dir = momentum_tool.DATA_DIR
        try:
            with tempfile.TemporaryDirectory() as temporary:
                momentum_tool.DATA_DIR = Path(temporary)
                config = {"network": {"daily_call_budgets": {"alpha_vantage": 1}}}

                class FakeResponse:
                    def __enter__(self):
                        return self

                    def __exit__(self, *_args):
                        return False

                    def read(self):
                        return json.dumps({"ok": True}).encode("utf-8")

                with patch.object(momentum_tool.urllib.request, "urlopen", return_value=FakeResponse()) as urlopen:
                    with patch.object(momentum_tool, "_wait_for_rate_limit"):
                        self.assertEqual(momentum_tool.http_json("https://example.test", config=config, namespace="alpha_vantage"), {"ok": True})
                        with self.assertRaisesRegex(RuntimeError, "orçamento diário local"):
                            momentum_tool.http_json("https://example.test/second", config=config, namespace="alpha_vantage")
                urlopen.assert_called_once()
                stats = momentum_tool.read_cache_stats()
                self.assertEqual(stats["daily_calls"]["alpha_vantage"]["calls"], 1)
        finally:
            momentum_tool.DATA_DIR = original_data_dir

    def test_outcome_summary_is_descriptive_and_grouped_by_horizon(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "outcomes.jsonl"
            rows = [
                {"outcome_version": 2, "mode": "demo", "symbol": "AI", "horizon": 5, "forward_return": 0.10},
                {"outcome_version": 2, "mode": "demo", "symbol": "AI", "horizon": 5, "forward_return": -0.02},
                {"outcome_version": 2, "mode": "live", "symbol": "AI", "horizon": 5, "forward_return": 0.99},
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            summary = momentum_tool.summarize_outcomes(path, "demo", [5, 20])
        self.assertEqual(summary["records"], 2)
        self.assertEqual(summary["by_horizon"]["5"]["positive_rate"], 0.5)
        self.assertEqual(summary["by_symbol"]["AI"]["5"]["records"], 2)
        self.assertIn("não é taxa de acerto", summary["note"])

    def test_sector_summary_is_ranked_and_counts_buy_signals(self):
        summary = momentum_tool.summarize_sectors([
            {"sector": "IA", "score": 80.0, "action": "Considerar compra"},
            {"sector": "IA", "score": 60.0, "action": "Manter/observar"},
            {"sector": "Cripto", "score": 40.0, "action": "Não agir"},
        ])
        self.assertEqual(summary[0]["sector"], "IA")
        self.assertEqual(summary[0]["average_score"], 70.0)
        self.assertEqual(summary[0]["buy_signals"], 1)

    def test_coinmarketcap_quotes_are_normalized(self):
        item = {"symbol": "BTC", "sector": "Cripto", "provider": "coinmarketcap", "source_id": "1"}
        payload = {
            "status": {"error_code": 0, "error_message": None},
            "data": [{
                "id": 1,
                "symbol": "BTC",
                "quotes": [{
                    "timestamp": "2026-08-01T23:59:59.999Z",
                    "quote": {"USD": {"price": 100.0, "volume_24h": 2500.0}},
                }],
            }],
        }
        with patch.dict(os.environ, {"COINMARKETCAP_API_KEY": "fixture-key"}):
            with patch.object(momentum_tool, "cached_http_json", return_value=payload) as request:
                rows = momentum_tool.fetch_coinmarketcap(item, self.config)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "coinmarketcap")
        self.assertEqual(rows[0]["source_id"], "1")
        self.assertEqual(rows[0]["close"], 100.0)
        self.assertEqual(rows[0]["volume"], 2500.0)
        self.assertIn("/v3/cryptocurrency/quotes/historical", request.call_args.args[0])
        self.assertIn("id=1", request.call_args.args[0])
        map_payload = {"status": payload["status"], "data": {"1": payload["data"][0]}}
        with patch.dict(os.environ, {"COINMARKETCAP_API_KEY": "fixture-key"}):
            with patch.object(momentum_tool, "cached_http_json", return_value=map_payload):
                mapped_rows = momentum_tool.fetch_coinmarketcap(item, self.config)
        self.assertEqual(mapped_rows[0]["close"], 100.0)

    def test_coinmarketcap_batches_multiple_ids_into_one_request(self):
        items = [
            {"symbol": "BTC", "sector": "Cripto", "provider": "coinmarketcap", "source_id": "1"},
            {"symbol": "ETH", "sector": "Cripto", "provider": "coinmarketcap", "source_id": "1027"},
        ]
        payload = {
            "status": {"error_code": 0},
            "data": {
                "1": {"id": 1, "symbol": "BTC", "quotes": [{"timestamp": "2026-08-01T00:00:00Z", "quote": {"USD": {"price": 100, "volume_24h": 10}}}]},
                "1027": {"id": 1027, "symbol": "ETH", "quotes": [{"timestamp": "2026-08-01T00:00:00Z", "quote": {"USD": {"price": 50, "volume_24h": 5}}}]},
            },
        }
        with patch.dict(os.environ, {"COINMARKETCAP_API_KEY": "fixture-key"}):
            with patch.object(momentum_tool, "cached_http_json", return_value=payload) as request:
                rows = momentum_tool.fetch_coinmarketcap_batch(items, self.config)
        self.assertEqual(rows["BTC"][0]["close"], 100.0)
        self.assertEqual(rows["ETH"][0]["close"], 50.0)
        self.assertIn("id=1%2C1027", request.call_args.args[0])

    def test_tiingo_eod_normalizes_adjusted_history(self):
        item = {"symbol": "AI", "sector": "IA", "provider": "tiingo", "source_id": "SOXX"}
        payload = [{
            "date": "2026-08-01T00:00:00.000Z",
            "close": 500.0,
            "adjClose": 499.5,
            "volume": 1000,
            "adjVolume": 1001,
        }]
        with patch.object(momentum_tool, "cached_http_json", return_value=payload) as request:
            rows = momentum_tool.fetch_tiingo(item, "fixture-key", self.config)
        self.assertEqual(rows[0]["source"], "tiingo")
        self.assertEqual(rows[0]["close"], 499.5)
        self.assertEqual(rows[0]["volume"], 1001.0)
        self.assertIn("/tiingo/daily/SOXX/prices", request.call_args.args[0])
        self.assertEqual(request.call_args.args[2], "tiingo")

    def test_tiingo_provider_is_counted_separately_from_alpha_quota(self):
        config = json.loads(json.dumps(self.config))
        config["universe"] = [{"symbol": "AI", "sector": "IA", "provider": "tiingo", "source_id": "SOXX"}]
        config["benchmark"] = {"provider": "tiingo", "source_id": "SPY"}
        config["news"] = {"provider": ""}
        config["macro"] = {"provider": "", "series": []}
        plan = momentum_tool.live_network_plan(config)
        self.assertEqual(plan["planned_calls_by_provider"]["tiingo"], 2)
        self.assertEqual(plan["planned_calls_by_quota_bucket"]["tiingo"], 2)
        self.assertIn("TIINGO_API_KEY", plan["missing_keys"])
        self.assertNotIn("ALPHAVANTAGE_API_KEY", plan["missing_keys"])

    def test_live_network_plan_bundles_coinmarketcap_universe(self):
        config = dict(self.config)
        config["universe"] = [
            {"symbol": "BTC", "provider": "coinmarketcap", "source_id": "1"},
            {"symbol": "ETH", "provider": "coinmarketcap", "source_id": "1027"},
        ]
        config["news"] = {"provider": ""}
        config["macro"] = {"provider": "", "series": []}
        plan = momentum_tool.live_network_plan(config)
        self.assertEqual(plan["planned_calls_by_provider"]["coinmarketcap"], 1)
        self.assertEqual(plan["estimated_total_calls"], 2)

    def test_live_network_plan_discounts_fresh_cache_by_exact_request(self):
        config = dict(self.config)
        config["universe"] = [{"symbol": "QQQ", "sector": "Mercado", "provider": "alpha_vantage", "source_id": "QQQ"}]
        config["news"] = {"provider": ""}
        config["macro"] = {"provider": "", "series": []}
        original_data_dir = momentum_tool.DATA_DIR
        try:
            with tempfile.TemporaryDirectory() as temporary:
                momentum_tool.DATA_DIR = Path(temporary)
                namespace, url = momentum_tool._live_request_specs(config)[0]
                cache_file = momentum_tool._cache_file_for_url(namespace, url)
                cache_file.parent.mkdir(parents=True)
                cache_file.write_text("{}", encoding="utf-8")
                plan = momentum_tool.live_network_plan(config)
        finally:
            momentum_tool.DATA_DIR = original_data_dir
        self.assertEqual(plan["estimated_total_calls"], 2)
        self.assertEqual(plan["estimated_network_calls"], 1)
        self.assertEqual(plan["cache_avoided_calls"], 1)

    def test_live_network_plan_deduplicates_asset_matching_global_benchmark(self):
        config = dict(self.config)
        config["universe"] = [{"symbol": "SPY", "sector": "Mercado", "provider": "alpha_vantage", "source_id": "SPY"}]
        config["news"] = {"provider": ""}
        config["macro"] = {"provider": "", "series": []}
        original_data_dir = momentum_tool.DATA_DIR
        try:
            with tempfile.TemporaryDirectory() as temporary:
                momentum_tool.DATA_DIR = Path(temporary)
                plan = momentum_tool.live_network_plan(config)
        finally:
            momentum_tool.DATA_DIR = original_data_dir
        self.assertEqual(plan["estimated_total_calls"], 2)
        self.assertEqual(plan["estimated_network_calls"], 1)
        self.assertEqual(plan["deduplicated_requests"], 1)

    def test_live_fetch_uses_one_coinmarketcap_batch_for_crypto_universe(self):
        config = dict(self.config)
        config["universe"] = [
            {"symbol": "BTC", "sector": "Cripto", "provider": "coinmarketcap", "source_id": "1"},
            {"symbol": "ETH", "sector": "Cripto", "provider": "coinmarketcap", "source_id": "1027"},
        ]
        config["news"] = {"provider": ""}
        config["macro"] = {"provider": "", "series": []}
        crypto_rows = {
            "BTC": [{"date": "2026-08-01", "symbol": "BTC", "sector": "Cripto", "close": 100, "volume": 10, "source": "coinmarketcap", "source_id": "1"}],
            "ETH": [{"date": "2026-08-01", "symbol": "ETH", "sector": "Cripto", "close": 50, "volume": 5, "source": "coinmarketcap", "source_id": "1027"}],
        }
        benchmark = [{"date": "2026-08-01", "symbol": "GLOBAL", "sector": "Benchmark global", "close": 100, "volume": 10, "source": "alpha_vantage", "source_id": "SPY"}]
        with patch.dict(os.environ, {"ALPHAVANTAGE_API_KEY": "alpha-fixture", "COINMARKETCAP_API_KEY": "cmc-fixture"}):
            with patch.object(momentum_tool, "fetch_coinmarketcap_batch", return_value=crypto_rows) as batch:
                with patch.object(momentum_tool, "fetch_alpha_vantage", return_value=benchmark):
                    rows, quality, _context = momentum_tool.fetch_live_data(config)
        batch.assert_called_once_with(config["universe"], config)
        self.assertEqual({row["symbol"] for row in rows}, {"BTC", "ETH", "GLOBAL"})
        self.assertEqual({row["symbol"] for row in quality}, {"BTC", "ETH", "GLOBAL"})

    def test_live_cohort_reuses_previous_live_rows_for_unselected_assets(self):
        config = dict(self.config)
        config["universe"] = [
            {"symbol": "AI", "sector": "IA", "provider": "alpha_vantage", "source_id": "SOXX"},
            {"symbol": "CLOUD", "sector": "Cloud", "provider": "alpha_vantage", "source_id": "SKYY"},
        ]
        config["news"] = {"provider": ""}
        config["macro"] = {"provider": "", "series": []}
        active_row = [{"date": "2026-08-13", "symbol": "AI", "sector": "IA", "close": 110, "volume": 10, "source": "alpha_vantage", "source_id": "SOXX"}]
        benchmark = [{"date": "2026-08-13", "symbol": "GLOBAL", "sector": "Benchmark global", "close": 100, "volume": 10, "source": "alpha_vantage", "source_id": "SPY"}]
        previous = {
            "meta": {"mode": "live", "as_of": "2026-08-12"},
            "history": [{"date": "2026-08-12", "symbol": "CLOUD", "sector": "Cloud", "close": 90, "volume": 8, "source": "alpha_vantage", "source_id": "SKYY"}],
            "quality": [{"symbol": "CLOUD", "source": "alpha_vantage", "status": "OK", "rows": 1}],
        }

        def fake_alpha(item, _key, _config):
            return benchmark if item["symbol"] == "GLOBAL" else active_row

        with patch.dict(os.environ, {"ALPHAVANTAGE_API_KEY": "alpha-fixture"}):
            with patch.object(momentum_tool, "fetch_alpha_vantage", side_effect=fake_alpha):
                rows, quality, _context = momentum_tool.fetch_live_data(config, {"AI"}, previous)
        self.assertEqual({row["symbol"] for row in rows}, {"AI", "CLOUD", "GLOBAL"})
        cloud_quality = next(item for item in quality if item["symbol"] == "CLOUD")
        self.assertEqual(cloud_quality["status"], "ATRASADO")
        self.assertIn("coorte", cloud_quality["message"])

    def test_live_cohort_marks_unvisited_assets_without_calling_them_errors(self):
        config = dict(self.config)
        config["universe"] = [
            {"symbol": "AI", "sector": "IA", "provider": "alpha_vantage", "source_id": "SOXX"},
            {"symbol": "CLOUD", "sector": "Cloud", "provider": "alpha_vantage", "source_id": "SKYY"},
        ]
        config["news"] = {"provider": ""}
        config["macro"] = {"provider": "", "series": []}
        active_row = [{"date": "2026-08-13", "symbol": "AI", "sector": "IA", "close": 110, "volume": 10, "source": "alpha_vantage", "source_id": "SOXX"}]
        benchmark = [{"date": "2026-08-13", "symbol": "GLOBAL", "sector": "Benchmark global", "close": 100, "volume": 10, "source": "alpha_vantage", "source_id": "SPY"}]

        def fake_alpha(item, _key, _config):
            return benchmark if item["symbol"] == "GLOBAL" else active_row

        with patch.dict(os.environ, {"ALPHAVANTAGE_API_KEY": "alpha-fixture"}):
            with patch.object(momentum_tool, "fetch_alpha_vantage", side_effect=fake_alpha):
                rows, quality, _context = momentum_tool.fetch_live_data(config, {"AI"}, {"meta": {"mode": "live"}, "history": [], "quality": []})
        self.assertEqual({row["symbol"] for row in rows}, {"AI", "GLOBAL"})
        cloud_quality = next(item for item in quality if item["symbol"] == "CLOUD")
        self.assertEqual(cloud_quality["status"], "FORA_DA_COORTE")
        quality_rows = momentum_tool.quality_rows(rows, config, quality)
        self.assertEqual(next(item for item in quality_rows if item["symbol"] == "CLOUD")["status"], "FORA_DA_COORTE")

    def test_live_network_plan_scopes_provider_calls_to_selected_cohort(self):
        config = dict(self.config)
        config["universe"] = [
            {"symbol": "AI", "provider": "alpha_vantage", "source_id": "SOXX"},
            {"symbol": "CLOUD", "provider": "alpha_vantage", "source_id": "SKYY"},
        ]
        config["news"] = {"provider": "", "query_tickers": []}
        config["macro"] = {"provider": "", "series": []}
        full = momentum_tool.live_network_plan(config)
        cohort = momentum_tool.live_network_plan(config, {"AI"})
        self.assertEqual(full["planned_calls_by_provider"]["alpha_vantage"], 3)
        self.assertEqual(cohort["planned_calls_by_provider"]["alpha_vantage"], 2)

    def test_alpha_price_can_use_explicit_keyless_yahoo_fallback(self):
        config = {
            "universe": [{"symbol": "AI", "sector": "IA", "provider": "alpha_vantage", "source_id": "SOXX"}],
            "benchmark": {"provider": "yahoo_finance", "source_id": "SPY"},
            "provider_fallbacks": {"alpha_vantage": ["yahoo_finance"]},
            "news": {"provider": "", "query_tickers": []},
            "macro": {"provider": "", "series": []},
            "lookback_days": 30,
        }

        def fake_yahoo(item, _config):
            return [{"date": "2026-08-13", "symbol": item["symbol"], "sector": item.get("sector", "Benchmark global"), "close": 100.0, "volume": 10.0, "source": "yahoo_finance", "source_id": item.get("source_id", item["symbol"])}]

        with patch.dict(os.environ, {"ALPHAVANTAGE_API_KEY": "", "TIINGO_API_KEY": ""}, clear=False):
            with patch.object(momentum_tool, "fetch_yahoo_finance", side_effect=fake_yahoo):
                rows, quality, _context = momentum_tool.fetch_live_data(config)
        self.assertEqual({row["symbol"] for row in rows}, {"AI", "GLOBAL"})
        ai_quality = next(item for item in quality if item["symbol"] == "AI")
        self.assertEqual(ai_quality["source"], "yahoo_finance")
        self.assertTrue(ai_quality["fallback_used"])
        self.assertEqual(ai_quality["provider_requested"], "alpha_vantage")
        self.assertEqual(ai_quality["provider_used"], "yahoo_finance")
        self.assertIn("defina ALPHAVANTAGE_API_KEY", ai_quality["message"])
        normalized = next(item for item in momentum_tool.quality_rows(rows, config, quality) if item["symbol"] == "AI")
        self.assertTrue(normalized["fallback_used"])
        self.assertEqual(normalized["provider_used"], "yahoo_finance")

    def test_live_plan_does_not_require_primary_key_when_keyless_fallback_exists(self):
        config = {
            "universe": [{"symbol": "AI", "sector": "IA", "provider": "alpha_vantage", "source_id": "SOXX"}],
            "benchmark": {"provider": "alpha_vantage", "source_id": "SPY"},
            "provider_fallbacks": {"alpha_vantage": ["yahoo_finance"]},
            "news": {"provider": "", "query_tickers": []},
            "macro": {"provider": "", "series": []},
            "cache": {"enabled": True, "ttl_seconds": 21600},
        }
        with patch.dict(os.environ, {"ALPHAVANTAGE_API_KEY": ""}, clear=False):
            plan = momentum_tool.live_network_plan(config)
        self.assertNotIn("ALPHAVANTAGE_API_KEY", plan["missing_keys"])
        self.assertTrue(plan["network_allowed"])
        self.assertEqual(plan["planned_calls_by_provider"]["yahoo_finance"], 2)
        self.assertNotIn("alpha_vantage", plan["planned_calls_by_provider"])

    def test_yahoo_finance_chart_is_normalized(self):
        item = {"symbol": "ASML", "sector": "Semicondutores", "provider": "yahoo_finance", "source_id": "ASML.AS"}
        payload = {
            "chart": {
                "result": [{
                    "meta": {"currency": "EUR"},
                    "timestamp": [1785628800],
                    "indicators": {"quote": [{"close": [100.5], "volume": [1234]}]},
                }],
                "error": None,
            }
        }
        with patch.object(momentum_tool, "cached_http_json", return_value=payload) as request:
            rows = momentum_tool.fetch_yahoo_finance(item, self.config)
        self.assertEqual(rows[0]["source"], "yahoo_finance")
        self.assertEqual(rows[0]["source_id"], "ASML.AS")
        self.assertEqual(rows[0]["currency"], "EUR")
        self.assertEqual(rows[0]["close"], 100.5)
        self.assertIn("query1.finance.yahoo.com", request.call_args.args[0])

    def test_yahoo_period_window_is_stable_within_one_utc_day(self):
        first = momentum_tool.yahoo_period_window(900, dt.datetime(2026, 8, 13, 8, 0, tzinfo=dt.timezone.utc))
        second = momentum_tool.yahoo_period_window(900, dt.datetime(2026, 8, 13, 19, 0, tzinfo=dt.timezone.utc))
        next_day = momentum_tool.yahoo_period_window(900, dt.datetime(2026, 8, 14, 8, 0, tzinfo=dt.timezone.utc))
        self.assertEqual(first, second)
        self.assertNotEqual(first, next_day)

    def test_live_network_plan_is_local_and_counts_context_calls(self):
        config = dict(self.config)
        config["universe"] = [
            {"symbol": "SPY", "provider": "alpha_vantage", "news_ticker": "SPY"},
            {"symbol": "BTC", "provider": "coinmarketcap"},
        ]
        config["news"] = {"provider": "alpha_vantage", "query_tickers": ["SPY"]}
        config["macro"] = {"provider": "fred", "series": [{"id": "VIXCLS"}, {"id": "DGS10"}]}
        config["network"] = {"daily_call_budgets": {"alpha_vantage": 25, "fred": 5, "coinmarketcap": 10}}
        with patch.dict(momentum_tool.os.environ, {}, clear=True):
            plan = momentum_tool.live_network_plan(config)
        self.assertEqual(plan["planned_calls_by_provider"]["yahoo_finance"], 2)
        self.assertNotIn("alpha_vantage", plan["planned_calls_by_provider"])
        self.assertEqual(plan["planned_calls_by_provider"]["news"], 1)
        self.assertEqual(plan["planned_calls_by_quota_bucket"]["alpha_vantage"], 1)
        self.assertEqual(plan["planned_calls_by_provider"]["fred"], 2)
        self.assertEqual(plan["estimated_total_calls"], 6)
        self.assertFalse(plan["network_allowed"])
        self.assertTrue(plan["missing_keys"])
        self.assertIn("Bloqueado antes da rede", plan["message"])
        self.assertIn("quota_advice", plan)
        advice = plan["quota_advice"]["alpha_vantage"]
        self.assertEqual(advice["news_requests_per_full_refresh"], 1)
        self.assertEqual(advice["reserve"], 0)
        self.assertGreaterEqual(advice["max_assets_in_safe_cohort"], 0)

    def test_live_network_plan_calculates_safe_alpha_cohort(self):
        config = dict(self.config)
        config["universe"] = [
            {"symbol": f"A{index}", "provider": "alpha_vantage", "source_id": f"A{index}"}
            for index in range(25)
        ]
        config["news"] = {"provider": "alpha_vantage", "query_tickers": ["A0"]}
        config["macro"] = {"provider": "", "series": []}
        config["network"] = {"daily_call_budgets": {"alpha_vantage": 25}, "daily_call_reserves": {"alpha_vantage": 5}}
        with patch.object(momentum_tool, "read_cache_stats", return_value={"daily_calls": {}}):
            plan = momentum_tool.live_network_plan(config)
        advice = plan["quota_advice"]["alpha_vantage"]
        self.assertEqual(advice["market_requests_per_full_refresh"], 26)
        self.assertEqual(advice["max_assets_in_safe_cohort"], 18)
        self.assertEqual(advice["estimated_rotation_days"], 2)
        self.assertIn("rota", advice["recommendation"])

    def test_live_network_plan_preserves_local_provider_reserve(self):
        config = dict(self.config)
        config["universe"] = [{"symbol": "A", "provider": "yahoo_finance", "source_id": "A"}]
        config["news"] = {"provider": "", "query_tickers": []}
        config["macro"] = {"provider": "", "series": []}
        config["network"] = {"daily_call_budgets": {"yahoo_finance": 1}, "daily_call_reserves": {"yahoo_finance": 1}}
        with patch.object(momentum_tool, "read_cache_stats", return_value={"daily_calls": {}}):
            plan = momentum_tool.live_network_plan(config)
        yahoo = next(row for row in plan["daily_budgets"] if row["provider"] == "yahoo_finance")
        self.assertEqual(yahoo["safe_remaining"], 0)
        self.assertEqual(yahoo["shortfall"], 1)
        self.assertFalse(plan["network_allowed"])

    def test_news_request_count_splits_market_and_crypto_groups(self):
        config = {"universe": [{"symbol": "SPY", "news_ticker": "SPY"}, {"symbol": "BTC", "news_ticker": "CRYPTO:BTC"}], "news": {"provider": "alpha_vantage"}}
        self.assertEqual(momentum_tool.news_request_count(config), 2)

    def test_fred_macro_context_produces_score_and_quality(self):
        fred_config = dict(self.config)
        fred_config["macro"] = {"series": [{"id": "VIXCLS"}, {"id": "T10Y2Y"}]}
        responses = [
            {"observations": [{"date": "2026-07-31", "value": "14.0"}]},
            {"observations": [{"date": "2026-07-31", "value": "0.30"}]},
        ]
        with patch.object(momentum_tool, "cached_http_json", side_effect=responses):
            score, series, quality = momentum_tool.fetch_fred_macro(fred_config, "fixture-key")
        self.assertGreater(score, 50.0)
        self.assertEqual(len(series), 2)
        self.assertTrue(all(row["status"] == "OK" for row in quality))


if __name__ == "__main__":
    unittest.main()
