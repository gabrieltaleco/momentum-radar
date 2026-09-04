import unittest

from src.metric_explanations import acquisition_analysis, metric_reading, personalized_metric_reading


class MetricExplanationTests(unittest.TestCase):
    def test_momentum_48_is_moderate_and_not_a_clear_entry(self):
        reading = metric_reading("momentum", 48.2)
        self.assertEqual(reading["band"], "40-59")
        self.assertEqual(reading["level"], "Moderado / neutro")
        self.assertIn("impulso claro", reading["meaning"])

    def test_risk_and_drawdown_use_different_scales(self):
        risk = metric_reading("risk_penalty", 22.1)
        drawdown = metric_reading("drawdown", 0.293)
        self.assertEqual(risk["level"], "Muito elevado")
        self.assertEqual(drawdown["level"], "Elevado")
        self.assertEqual(drawdown["band"], "15-29.9%")

    def test_relative_strength_explains_benchmark_comparison(self):
        reading = metric_reading("relative_strength", 37.6)
        self.assertEqual(reading["level"], "Abaixo do mercado")
        self.assertIn("mercado de comparação", reading["meaning"])

    def test_personalized_volume_does_not_invent_panic_selling(self):
        reading = personalized_metric_reading(
            "volume",
            74.6,
            {"symbol": "SLV", "name": "iShares Silver Trust", "sector": "Metais preciosos"},
            {"momentum": 48.2, "trend": 46.9},
        )
        self.assertIn("iShares Silver Trust", reading["personalized_meaning"])
        self.assertIn("não diz se predominam compras ou vendas", reading["personalized_meaning"])

    def test_acquisition_analysis_calculates_loss_and_recovery(self):
        reading = acquisition_analysis(100, 75, "Reduzir/evitar", "Prata")
        self.assertTrue(reading["available"])
        self.assertAlmostEqual(reading["pnl_pct"], -0.25)
        self.assertAlmostEqual(reading["break_even_recovery_pct"], 1 / 3)
        self.assertEqual(reading["level"], "Muito abaixo do custo")
        self.assertIn("33.3%", reading["meaning"])

    def test_acquisition_analysis_does_not_fake_missing_cost(self):
        reading = acquisition_analysis(0, 100, "Manter/observar", "ETF")
        self.assertFalse(reading["available"])
        self.assertIn("não está disponível", reading["meaning"])


if __name__ == "__main__":
    unittest.main()
