import tempfile
import unittest
from pathlib import Path

from autohedge.portfolio import PaperPortfolio
from autohedge.risk_engine import RiskEngine, RiskLimits
from autohedge.schemas import KeyLevels, QuantAnalysis, Thesis


def make_thesis(**overrides) -> Thesis:
    defaults = dict(
        ticker="NVDA",
        direction="long",
        summary="strong momentum",
        confidence=0.8,
    )
    defaults.update(overrides)
    return Thesis(**defaults)


def make_quant(**overrides) -> QuantAnalysis:
    defaults = dict(
        ticker="NVDA",
        technical_score=0.7,
        volume_score=0.7,
        trend_strength=0.7,
        volatility=0.2,
        probability_score=0.7,
        key_levels=KeyLevels(support=90.0, resistance=120.0, pivot=100.0),
        current_price=100.0,
    )
    defaults.update(overrides)
    return QuantAnalysis(**defaults)


class TestRiskEngine(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tmpdir.name) / "portfolio.json"
        self.portfolio = PaperPortfolio(path=self.path, starting_cash=100_000.0)
        self.engine = RiskEngine(RiskLimits())

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_approves_healthy_trade_with_sane_position_size(self):
        decision = self.engine.evaluate(
            make_thesis(), make_quant(), self.portfolio
        )
        self.assertTrue(decision.approved)
        self.assertEqual(decision.position_size_usd, 10_000.0)  # 10% of 100k
        self.assertEqual(decision.stop_loss_price, 90.0)
        self.assertEqual(decision.take_profit_price, 120.0)

    def test_rejects_low_probability_score(self):
        decision = self.engine.evaluate(
            make_thesis(),
            make_quant(probability_score=0.2),
            self.portfolio,
        )
        self.assertFalse(decision.approved)
        self.assertIn("probability_score", decision.reasons[0])

    def test_rejects_when_daily_loss_limit_hit(self):
        # Simulate a portfolio that's already down 5% today (limit is 3%).
        self.portfolio._start_of_day_equity = 105_000.0  # equity is 100k
        decision = self.engine.evaluate(
            make_thesis(), make_quant(), self.portfolio
        )
        self.assertFalse(decision.approved)
        self.assertEqual(decision.position_size_usd, 0.0)
        self.assertIn("daily loss limit", decision.reasons[0])

    def test_rejects_when_max_open_positions_reached(self):
        engine = RiskEngine(RiskLimits(max_open_positions=0))
        decision = engine.evaluate(make_thesis(), make_quant(), self.portfolio)
        self.assertFalse(decision.approved)
        self.assertTrue(
            any("max open positions" in r for r in decision.reasons)
        )

    def test_position_size_capped_by_total_exposure_limit(self):
        engine = RiskEngine(
            RiskLimits(max_position_pct=0.5, max_total_exposure_pct=0.1)
        )
        decision = engine.evaluate(make_thesis(), make_quant(), self.portfolio)
        self.assertTrue(decision.approved)
        self.assertEqual(decision.position_size_usd, 10_000.0)  # 10% cap wins

    def test_short_thesis_flips_stop_and_take_profit(self):
        decision = self.engine.evaluate(
            make_thesis(direction="short"), make_quant(), self.portfolio
        )
        self.assertEqual(decision.stop_loss_price, 120.0)
        self.assertEqual(decision.take_profit_price, 90.0)

    def test_falls_back_to_pct_levels_when_key_levels_invalid(self):
        quant = make_quant(
            key_levels=KeyLevels(support=0.0, resistance=0.0, pivot=100.0)
        )
        decision = self.engine.evaluate(make_thesis(), quant, self.portfolio)
        self.assertAlmostEqual(decision.stop_loss_price, 95.0)
        self.assertAlmostEqual(decision.take_profit_price, 110.0)


if __name__ == "__main__":
    unittest.main()
