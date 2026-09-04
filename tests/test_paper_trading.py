import unittest
import json
import datetime as dt
from tempfile import TemporaryDirectory

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from paper_trading import apply_matrix_signals, apply_signals, load_state, paper_coverage, review_progress, write_outputs  # noqa: E402


class PaperTradingTests(unittest.TestCase):
    def test_matrix_allows_same_asset_in_different_horizon_slots(self):
        signal = {
            "symbol": "AAA", "sector": "IA", "price": 100.0, "confidence": 90.0,
            "data_points": 900, "volatility_annual": 0.20, "action": "Manter/observar",
            "horizons": {
                "short": {"score": 65.0, "action": "Acompanhar / entrada pequena"},
                "medium": {"score": 75.0, "action": "Entrada faseada"},
                "long": {"score": 85.0, "action": "Entrada faseada"},
            },
        }
        base = {"config": {"thresholds": {"paper_entry_matrix": {"enabled": True, "max_new_entries": 1}}, "universe": []}, "signals": [signal], "meta": {"as_of": "2026-08-01"}}
        state = apply_matrix_signals(load_state(Path("missing-matrix-state.json"), 100000.0), base)
        self.assertEqual(list(state["positions"]), ["AAA::short"])
        base["meta"] = {"as_of": "2026-08-02"}
        state = apply_matrix_signals(state, base)
        self.assertIn("AAA::medium", state["positions"])
        self.assertEqual(len(state["trades"]), 2)
        self.assertEqual({trade["horizon"] for trade in state["trades"]}, {"short", "medium"})

    def test_matrix_records_explicit_nine_cells_and_aggregated_limits(self):
        payload = {
            "meta": {"as_of": "2026-08-01"},
            "config": {"thresholds": {"paper_entry_matrix": {"enabled": True, "max_new_entries": 9}}, "universe": []},
            "signals": [{"symbol": "AAA", "sector": "IA", "price": 100.0, "confidence": 90.0, "data_points": 900, "action": "Manter/observar", "horizons": {"short": {"score": 85.0}, "medium": {"score": 85.0}, "long": {"score": 85.0}}}],
        }
        state = apply_matrix_signals(load_state(Path("missing-matrix-state.json"), 100000.0), payload)
        review = state["last_entry_review"]
        self.assertEqual(len(review["cells"]), 9)
        self.assertEqual(len(state["positions"]), 3)
        self.assertLessEqual(sum(float(item["shares"]) * float(item["entry_price"]) for item in state["positions"].values()), 6000.0)

    def test_ladder_uses_score_tier_and_risk_adjusted_cap(self):
        payload = {
            "meta": {"as_of": "2026-08-01"},
            "config": {"thresholds": {"paper_entry_ladder": {
                "enabled": True,
                "min_confidence": 70,
                "max_new_entries": 2,
                "cash_floor_pct": 0.5,
                "max_total_exposure_pct": 0.4,
                "max_position_pct": 0.04,
                "max_sector_pct": 0.15,
                "tiers": [
                    {"name": "exploratoria", "min_score": 60, "max_score": 70, "horizon_days": 5, "allocation_pct": 0.005, "risk_pct": 0.0005},
                    {"name": "confirmada", "min_score": 70, "max_score": 80, "horizon_days": 20, "allocation_pct": 0.02, "risk_pct": 0.0015},
                ]
            }}},
            "signals": [{"symbol": "AI", "sector": "IA", "price": 100.0, "score": 65.0, "confidence": 90.0, "data_points": 900, "volatility_annual": 0.20, "action": "Manter/observar"}],
        }
        updated = apply_signals(load_state(Path("missing-paper-state.json"), 100000.0), payload)
        self.assertAlmostEqual(updated["cash"], 99500.0)
        self.assertEqual(updated["positions"]["AI"]["entry_policy"], "paper-ladder-v1")
        self.assertEqual(updated["positions"]["AI"]["entry_tier"], "exploratoria")
        self.assertEqual(updated["positions"]["AI"]["entry_horizon_days"], 5)
        self.assertIn("escada exploratoria", updated["trades"][0]["reason"])

    def test_ladder_keeps_low_quality_signals_out(self):
        payload = {
            "meta": {"as_of": "2026-08-01"},
            "config": {"thresholds": {"paper_entry_ladder": {"enabled": True, "min_confidence": 70}}},
            "signals": [{"symbol": "AI", "sector": "IA", "price": 100.0, "score": 65.0, "confidence": 69.9, "data_points": 900, "action": "Manter/observar"}],
        }
        updated = apply_signals(load_state(Path("missing-paper-state.json"), 100000.0), payload)
        self.assertEqual(updated["trades"], [])
        self.assertEqual(updated["positions"], {})

    def test_portfolio_monitor_signals_do_not_enter_paper_ledger(self):
        payload = {
            "meta": {"as_of": "2026-08-01"},
            "config": {"thresholds": {"max_position_pct": 0.1, "max_sector_pct": 0.2}, "universe": [{"symbol": "REAL", "portfolio_monitor_only": True}]},
            "signals": [
                {"symbol": "REAL", "sector": "Carteira", "price": 100.0, "action": "Considerar compra"},
                {"symbol": "CORE", "sector": "Radar", "price": 100.0, "action": "Considerar compra"},
            ],
        }
        updated = apply_signals(load_state(Path("missing-paper-state.json"), 10000.0), payload)
        self.assertEqual([item["symbol"] for item in updated["trades"]], ["CORE"])
        self.assertNotIn("REAL", updated["positions"])

    def test_buy_respects_position_cap_and_is_idempotent(self):
        payload = {
            "meta": {"as_of": "2026-08-01"},
            "config": {"thresholds": {"max_position_pct": 0.1, "max_sector_pct": 0.2}},
            "signals": [{"symbol": "AI", "sector": "IA", "price": 100.0, "action": "Considerar compra"}],
        }
        state = load_state(Path("missing-paper-state.json"), 10000.0)
        updated = apply_signals(state, payload)
        self.assertAlmostEqual(updated["cash"], 9000.0)
        self.assertEqual(len(updated["trades"]), 1)
        self.assertEqual(len(updated["runs"]), 1)
        self.assertTrue(updated["runs"][0]["processed"])
        again = apply_signals(updated, payload)
        self.assertEqual(len(again["trades"]), 1)
        self.assertEqual(len(again["runs"]), 2)
        self.assertFalse(again["runs"][1]["processed"])

    def test_reduce_sells_existing_position(self):
        payload = {
            "meta": {"as_of": "2026-08-02"},
            "config": {"thresholds": {"max_position_pct": 0.1, "max_sector_pct": 0.2}},
            "signals": [{"symbol": "AI", "sector": "IA", "price": 110.0, "action": "Reduzir/evitar"}],
        }
        state = {"initial_cash": 10000.0, "cash": 9000.0, "positions": {"AI": {"shares": 10.0, "entry_price": 100.0, "last_price": 100.0, "sector": "IA"}}, "trades": [], "snapshots": []}
        updated = apply_signals(state, payload)
        self.assertNotIn("AI", updated["positions"])
        self.assertAlmostEqual(updated["cash"], 10100.0)
        self.assertEqual(updated["trades"][0]["action"], "SELL")

    def test_write_outputs_supports_separate_portfolio_prefix(self):
        with TemporaryDirectory() as output_dir:
            write_outputs({"initial_cash": 100000.0, "cash": 100000.0, "positions": {}, "trades": [], "snapshots": []}, Path(output_dir), "paper-week-100k")
            self.assertTrue((Path(output_dir) / "paper-week-100k_portfolio.json").exists())
            self.assertTrue((Path(output_dir) / "paper-week-100k_trades.csv").exists())
            self.assertTrue((Path(output_dir) / "paper-week-100k-report.md").exists())
            self.assertTrue((Path(output_dir) / "paper-week-100k_status.json").exists())

    def test_review_progress_counts_processed_snapshots(self):
        state = {
            "snapshots": [
                {"date": "2026-08-01", "signals": 10},
                {"date": "2026-08-02", "signals": 10},
            ],
            "runs": [{"processed": True}, {"processed": False}],
        }
        progress = review_progress(state)
        self.assertEqual(progress["snapshots"], 2)
        self.assertEqual(progress["decision_records"], 20)
        self.assertEqual(progress["target_snapshots"], 60)
        self.assertEqual(progress["target_decisions"], 50)
        self.assertFalse(progress["ready_for_review"])
        self.assertIn("Faltam", progress["message"])

    def test_paper_coverage_identifies_missing_potential_weekdays(self):
        coverage = paper_coverage({
            "snapshots": [
                {"date": "2026-08-04"},
                {"date": "2026-08-06"},
                {"date": "2026-08-11"},
                {"date": "2026-08-13"},
            ]
        })
        self.assertTrue(coverage["available"])
        self.assertEqual(coverage["observed_snapshots"], 4)
        self.assertEqual(coverage["potential_weekdays"], 8)
        self.assertEqual(coverage["coverage_pct"], 50.0)
        self.assertEqual(coverage["missing_potential_dates"], ["2026-08-05", "2026-08-07", "2026-08-10", "2026-08-12"])

    def test_write_outputs_includes_operational_coverage(self):
        with TemporaryDirectory() as output_dir:
            write_outputs({
                "initial_cash": 100000.0,
                "cash": 100000.0,
                "positions": {},
                "trades": [],
                "snapshots": [
                    {"date": "2026-08-04", "cash": 100000.0, "equity": 100000.0, "positions": 0, "signals": 0},
                    {"date": "2026-08-06", "cash": 100000.0, "equity": 100000.0, "positions": 0, "signals": 0},
                ],
            }, Path(output_dir), "paper")
            report = (Path(output_dir) / "paper-report.md").read_text(encoding="utf-8")
            status = json.loads((Path(output_dir) / "paper_status.json").read_text(encoding="utf-8"))
            self.assertIn("Cobertura operacional", report)
            self.assertEqual(status["review_progress"]["coverage"]["potential_weekdays"], 3)

    def test_review_progress_requires_time_and_decision_targets(self):
        progress = review_progress({"snapshots": [{"date": "2026-08-01", "signals": 50}]})
        self.assertFalse(progress["ready_for_review"])
        self.assertEqual(progress["decision_progress_pct"], 100.0)
        self.assertIn("59 snapshots", progress["message"])

        start = dt.date(2026, 1, 1)
        mature = review_progress({"snapshots": [
            {"date": (start + dt.timedelta(days=index)).isoformat(), "signals": 1}
            for index in range(60)
        ]})
        self.assertTrue(mature["ready_for_review"])

    def test_same_market_date_is_idempotent_but_run_is_recorded(self):
        payload = {
            "meta": {"as_of": "2026-08-03", "mode": "live"},
            "config": {"thresholds": {"max_position_pct": 0.1, "max_sector_pct": 0.2}},
            "signals": [],
        }
        state = load_state(Path("missing-paper-state.json"), 100000.0)
        first = apply_signals(state, payload)
        second = apply_signals(first, payload)
        self.assertEqual(len(second["snapshots"]), 1)
        self.assertEqual(len(second["runs"]), 2)
        self.assertFalse(second["runs"][-1]["processed"])
        self.assertEqual(second["last_entry_review"]["status"], "duplicate")

    def test_older_market_date_is_rejected_without_reordering_ledger(self):
        state = load_state(Path("missing-paper-state.json"), 100000.0)
        newer = {
            "meta": {"as_of": "2026-08-04", "mode": "live"},
            "config": {"thresholds": {"max_position_pct": 0.1, "max_sector_pct": 0.2}},
            "signals": [],
        }
        older = {**newer, "meta": {"as_of": "2026-08-03", "mode": "live"}}
        state = apply_signals(state, newer)
        state = apply_signals(state, older)
        self.assertEqual(state["last_date"], "2026-08-04")
        self.assertEqual(len(state["snapshots"]), 1)
        self.assertEqual(state["last_entry_review"]["status"], "out_of_order")

    def test_zero_entry_snapshot_explains_missing_buy_signal_and_short_history(self):
        payload = {
            "meta": {"as_of": "2026-08-03", "mode": "live"},
            "config": {"thresholds": {"max_position_pct": 0.1, "max_sector_pct": 0.2}},
            "signals": [
                {"symbol": "AI", "sector": "IA", "price": 100.0, "data_points": 100, "action": "Não agir"},
                {"symbol": "BTC", "sector": "Cripto", "price": 200.0, "data_points": 365, "action": "Reduzir/evitar"},
            ],
        }
        state = apply_signals(load_state(Path("missing-paper-state.json"), 100000.0), payload)
        review = state["last_entry_review"]
        self.assertEqual(review["entries"], 0)
        codes = {item["code"] for item in review["blockers"]}
        self.assertIn("no_buy_signal", codes)
        self.assertIn("insufficient_history", codes)

    def test_entry_review_explains_score_gap_and_weak_factors(self):
        payload = {
            "meta": {"as_of": "2026-08-03"},
            "config": {"thresholds": {"buy_score": 80, "hold_score": 55, "max_position_pct": 0.1, "max_sector_pct": 0.2}},
            "signals": [{
                "symbol": "CLOUD",
                "sector": "Cloud",
                "price": 100.0,
                "data_points": 900,
                "score": 60.0,
                "action": "Manter/observar",
                "momentum": 72.0,
                "relative_strength": 69.0,
                "trend": 77.0,
                "volume": 34.0,
                "news": 50.0,
                "macro": 78.0,
                "risk_penalty": 5.4,
            }],
        }
        state = apply_signals(load_state(Path("missing-paper-state.json"), 100000.0), payload)
        review = state["last_entry_review"]
        candidate = review["near_entry_candidates"][0]
        self.assertEqual(candidate["gap_to_buy"], 20.0)
        self.assertIn("volume", candidate["watch_factors"])
        self.assertIn("below_buy_threshold", {item["code"] for item in review["blockers"]})

    def test_strict_live_quality_blocks_signals_without_mutating_portfolio(self):
        payload = {
            "meta": {"as_of": "2026-08-04", "mode": "live"},
            "config": {"universe": [{"symbol": "AI"}], "thresholds": {"max_position_pct": 0.1, "max_sector_pct": 0.2}},
            "quality": [{"symbol": "GLOBAL", "status": "OK"}, {"symbol": "AI", "status": "ERRO"}],
            "signals": [{"symbol": "AI", "sector": "IA", "price": 100.0, "action": "Considerar compra"}],
        }
        state = load_state(Path("missing-paper-state.json"), 100000.0)
        updated = apply_signals(state, payload, strict_live_quality=True)
        self.assertEqual(updated["cash"], 100000.0)
        self.assertEqual(updated["positions"], {})
        self.assertEqual(updated["snapshots"], [])
        self.assertFalse(updated["runs"][-1]["processed"])
        self.assertIn("qualidade live bloqueada", updated["runs"][-1]["reason"])

    def test_execution_costs_are_applied_to_buy_and_sell(self):
        buy_payload = {
            "meta": {"as_of": "2026-08-04", "mode": "live"},
            "config": {
                "backtest": {"commission_bps": 100.0, "slippage_bps": 100.0},
                "thresholds": {"max_position_pct": 0.1, "max_sector_pct": 0.2},
            },
            "signals": [{"symbol": "AI", "sector": "IA", "price": 100.0, "action": "Considerar compra"}],
        }
        state = apply_signals(load_state(Path("missing-paper-state.json"), 10000.0), buy_payload)
        trade = state["trades"][0]
        self.assertAlmostEqual(trade["reference_price"], 100.0)
        self.assertAlmostEqual(trade["price"], 101.0)
        self.assertGreater(trade["fees"], 0.0)
        self.assertLessEqual(state["cash"] + trade["notional"] + trade["fees"], 10000.0 + 1e-6)

        sell_payload = {
            "meta": {"as_of": "2026-08-05", "mode": "live"},
            "config": {
                "backtest": {"commission_bps": 100.0, "slippage_bps": 100.0},
                "thresholds": {"max_position_pct": 0.1, "max_sector_pct": 0.2},
            },
            "signals": [{"symbol": "AI", "sector": "IA", "price": 110.0, "action": "Reduzir/evitar"}],
        }
        sold = apply_signals(state, sell_payload)
        self.assertNotIn("AI", sold["positions"])
        self.assertEqual(sold["trades"][-1]["action"], "SELL")
        self.assertAlmostEqual(sold["trades"][-1]["price"], 108.9, places=4)
        self.assertGreater(sold["trades"][-1]["fees"], 0.0)

    def test_drawdown_brake_blocks_new_buys_but_keeps_state_auditable(self):
        payload = {
            "meta": {"as_of": "2026-08-06"},
            "config": {"thresholds": {"max_position_pct": 0.1, "max_sector_pct": 0.2, "paper_drawdown_brake_pct": 0.15}},
            "signals": [{"symbol": "AI", "sector": "IA", "price": 80.0, "action": "Considerar compra"}],
        }
        state = {
            "initial_cash": 10000.0,
            "cash": 8500.0,
            "peak_equity": 10000.0,
            "positions": {"OLD": {"shares": 1.0, "entry_price": 0.0, "last_price": 0.0, "sector": "Outro"}},
            "trades": [],
            "snapshots": [],
        }
        updated = apply_signals(state, payload)
        self.assertNotIn("AI", updated["positions"])
        self.assertTrue(updated["last_risk_control"]["active"])
        self.assertGreaterEqual(updated["snapshots"][-1]["portfolio_drawdown"], 0.15)


if __name__ == "__main__":
    unittest.main()
