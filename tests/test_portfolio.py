import tempfile
import unittest
from pathlib import Path

from autohedge.portfolio import PaperPortfolio
from autohedge.schemas import ExecutionOrder


def make_order(**overrides) -> ExecutionOrder:
    defaults = dict(
        ticker="NVDA",
        side="buy",
        order_type="market",
        quantity=10,
        entry_price=100.0,
        stop_loss=90.0,
        take_profit=120.0,
    )
    defaults.update(overrides)
    return ExecutionOrder(**defaults)


class TestPaperPortfolio(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tmpdir.name) / "portfolio.json"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_starts_with_full_cash_and_no_positions(self):
        pf = PaperPortfolio(path=self.path, starting_cash=100_000.0)
        self.assertEqual(pf.cash, 100_000.0)
        self.assertEqual(pf.total_equity(), 100_000.0)
        self.assertEqual(pf.positions, {})

    def test_buy_reduces_cash_and_opens_position(self):
        pf = PaperPortfolio(path=self.path, starting_cash=100_000.0)
        pf.fill(make_order(quantity=10), fill_price=100.0)

        self.assertEqual(pf.cash, 99_000.0)
        self.assertTrue(pf.has_position("NVDA"))
        self.assertEqual(pf.positions["NVDA"].quantity, 10)
        self.assertEqual(pf.total_equity(), 100_000.0)

    def test_buy_rejects_insufficient_cash(self):
        pf = PaperPortfolio(path=self.path, starting_cash=100.0)
        with self.assertRaises(ValueError):
            pf.fill(make_order(quantity=10), fill_price=100.0)

    def test_sell_closes_position_and_returns_cash(self):
        pf = PaperPortfolio(path=self.path, starting_cash=100_000.0)
        pf.fill(make_order(quantity=10), fill_price=100.0)
        pf.fill(make_order(side="sell", quantity=10), fill_price=110.0)

        self.assertFalse(pf.has_position("NVDA"))
        self.assertEqual(pf.cash, 100_000.0 - 1000.0 + 1100.0)

    def test_sell_rejects_oversized_close(self):
        pf = PaperPortfolio(path=self.path, starting_cash=100_000.0)
        pf.fill(make_order(quantity=5), fill_price=100.0)
        with self.assertRaises(ValueError):
            pf.fill(make_order(side="sell", quantity=10), fill_price=100.0)

    def test_state_persists_across_instances(self):
        pf = PaperPortfolio(path=self.path, starting_cash=100_000.0)
        pf.fill(make_order(quantity=10), fill_price=100.0)

        pf2 = PaperPortfolio(path=self.path, starting_cash=100_000.0)
        self.assertEqual(pf2.cash, 99_000.0)
        self.assertTrue(pf2.has_position("NVDA"))
        self.assertEqual(len(pf2.history), 1)

    def test_total_exposure_uses_last_price(self):
        pf = PaperPortfolio(path=self.path, starting_cash=100_000.0)
        pf.fill(make_order(quantity=10), fill_price=100.0)
        pf.update_price("NVDA", 150.0)
        self.assertEqual(pf.total_exposure_usd(), 1500.0)
        self.assertEqual(pf.total_equity(), 99_000.0 + 1500.0)


if __name__ == "__main__":
    unittest.main()
