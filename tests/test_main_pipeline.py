"""
End-to-end orchestration tests for AutoHedge.run(), with the LLM agents
and live market data lookup mocked out. This exercises the real control flow
(director -> quant -> RiskEngine -> execution -> paper fill) without
making any network or LLM calls.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autohedge.main import AutoHedge
from autohedge.risk_engine import RiskLimits

THESIS_JSON = json.dumps(
    {
        "ticker": "NVDA",
        "direction": "long",
        "summary": "strong AI demand momentum",
        "confidence": 0.8,
        "key_factors": ["datacenter revenue growth"],
        "risks": ["valuation risk"],
    }
)

QUANT_JSON = json.dumps(
    {
        "ticker": "NVDA",
        "technical_score": 0.75,
        "volume_score": 0.7,
        "trend_strength": 0.8,
        "volatility": 0.3,
        "probability_score": 0.7,
        "key_levels": {"support": 90.0, "resistance": 120.0, "pivot": 100.0},
        "current_price": 100.0,
    }
)

ORDER_JSON_TEMPLATE = json.dumps(
    {
        "ticker": "NVDA",
        "side": "buy",
        "order_type": "market",
        "quantity": 100.0,  # 10_000 / 100.0
        "entry_price": 100.0,
        "stop_loss": 90.0,
        "take_profit": 120.0,
        "time_in_force": "day",
    }
)


class TestAutoHedgePipeline(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.portfolio_path = Path(self.tmpdir.name) / "portfolio.json"
        self.output_dir = Path(self.tmpdir.name) / "outputs"

        self.system = AutoHedge(
            output_dir=str(self.output_dir),
            portfolio_path=str(self.portfolio_path),
            starting_cash=100_000.0,
            risk_limits=RiskLimits(min_probability_score=0.5),
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    @patch("autohedge.main.get_market_snapshot", return_value={"symbol": "NVDA", "current_price": 100.0, "volume": 1000, "avg_volume_1mo": 900, "high_1mo": 110.0, "low_1mo": 90.0, "prev_close": 99.0})
    @patch("autohedge.main.execution_agent")
    @patch("autohedge.main.quant_agent")
    @patch("autohedge.main.director_agent")
    @patch("autohedge.main.ticker_discovery_agent")
    def test_full_cycle_fills_a_paper_trade(
        self,
        mock_discovery,
        mock_director,
        mock_quant,
        mock_execution,
        _mock_price,
    ):
        mock_discovery.run.return_value = '["NVDA"]'
        mock_director.run.return_value = THESIS_JSON
        mock_director.agent_name = "Trading-Director"
        mock_quant.run.return_value = QUANT_JSON
        mock_quant.agent_name = "Quant-Analyst"
        mock_execution.run.return_value = ORDER_JSON_TEMPLATE
        mock_execution.agent_name = "Execution-Agent"

        results = self.system.run("Analyze NVDA for a swing trade")

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result["status"], "filled")
        self.assertIn("fill", result)
        self.assertEqual(result["fill"]["ticker"], "NVDA")
        self.assertEqual(result["fill"]["mode"], "paper")

        # Portfolio actually changed on disk.
        self.assertTrue(self.system.portfolio.has_position("NVDA"))
        self.assertLess(self.system.portfolio.cash, 100_000.0)

    @patch("autohedge.main.get_market_snapshot", return_value={"symbol": "NVDA", "current_price": 100.0, "volume": 1000, "avg_volume_1mo": 900, "high_1mo": 110.0, "low_1mo": 90.0, "prev_close": 99.0})
    @patch("autohedge.main.execution_agent")
    @patch("autohedge.main.quant_agent")
    @patch("autohedge.main.director_agent")
    @patch("autohedge.main.ticker_discovery_agent")
    def test_low_probability_trade_is_rejected_before_execution(
        self,
        mock_discovery,
        mock_director,
        mock_quant,
        mock_execution,
        _mock_price,
    ):
        low_prob_quant = json.loads(QUANT_JSON)
        low_prob_quant["probability_score"] = 0.1
        mock_discovery.run.return_value = '["NVDA"]'
        mock_director.run.return_value = THESIS_JSON
        mock_director.agent_name = "Trading-Director"
        mock_quant.run.return_value = json.dumps(low_prob_quant)
        mock_quant.agent_name = "Quant-Analyst"

        results = self.system.run("Analyze NVDA")

        self.assertEqual(results[0]["status"], "rejected")
        self.assertFalse(mock_execution.run.called)
        self.assertFalse(self.system.portfolio.has_position("NVDA"))

    @patch("autohedge.main.get_market_snapshot", return_value={"symbol": "NVDA", "current_price": 100.0, "volume": 1000, "avg_volume_1mo": 900, "high_1mo": 110.0, "low_1mo": 90.0, "prev_close": 99.0})
    @patch("autohedge.main.execution_agent")
    @patch("autohedge.main.quant_agent")
    @patch("autohedge.main.director_agent")
    @patch("autohedge.main.ticker_discovery_agent")
    def test_execution_agent_exceeding_position_size_is_rejected(
        self,
        mock_discovery,
        mock_director,
        mock_quant,
        mock_execution,
        _mock_price,
    ):
        oversized_order = json.loads(ORDER_JSON_TEMPLATE)
        oversized_order["quantity"] = 10_000.0  # far beyond approved size
        mock_discovery.run.return_value = '["NVDA"]'
        mock_director.run.return_value = THESIS_JSON
        mock_director.agent_name = "Trading-Director"
        mock_quant.run.return_value = QUANT_JSON
        mock_quant.agent_name = "Quant-Analyst"
        mock_execution.run.return_value = json.dumps(oversized_order)
        mock_execution.agent_name = "Execution-Agent"

        results = self.system.run("Analyze NVDA")

        self.assertIn("error", results[0])
        self.assertIn("exceeds approved position size", results[0]["error"])
        self.assertFalse(self.system.portfolio.has_position("NVDA"))

    @patch("autohedge.main.ticker_discovery_agent")
    def test_ticker_discovery_failure_surfaces_the_real_reason(
        self, mock_discovery
    ):
        # Reproduces a real failure: the LLM call itself raised (e.g. a
        # rate limit), and run() used to swallow this into a silent
        # empty list with no indication of why.
        mock_discovery.run.side_effect = RuntimeError("429 rate limited")

        results = self.system.run("Analyze NVDA")

        self.assertEqual(len(results), 1)
        self.assertIn("error", results[0])
        self.assertIn("rate limited", results[0]["error"])

    @patch("autohedge.main.ticker_discovery_agent")
    def test_empty_ticker_list_surfaces_a_reason_not_silence(
        self, mock_discovery
    ):
        mock_discovery.run.return_value = "[]"

        results = self.system.run("Analyze the weather")

        self.assertEqual(len(results), 1)
        self.assertIn("error", results[0])


if __name__ == "__main__":
    unittest.main()
