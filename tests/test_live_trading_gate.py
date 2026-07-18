"""
Live trading must stay off unless explicitly, deliberately enabled.
No network calls are made here: the gate check must fail before
autohedge.live ever reaches ultra_tools.get_order.
"""

import os
import unittest
from unittest.mock import patch

from autohedge.live import LiveTradingDisabledError, execute_live_swap


class TestLiveTradingGate(unittest.TestCase):
    def test_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AUTOHEDGE_ENABLE_LIVE_TRADING", None)
            with self.assertRaises(LiveTradingDisabledError):
                execute_live_swap("mintA", "mintB", "1000")

    def test_disabled_for_wrong_value(self):
        with patch.dict(
            os.environ, {"AUTOHEDGE_ENABLE_LIVE_TRADING": "true"}
        ):
            with self.assertRaises(LiveTradingDisabledError):
                execute_live_swap("mintA", "mintB", "1000")

    @patch("autohedge.live.execute_trade", return_value='{"status": "Success"}')
    @patch(
        "autohedge.live.get_order",
        return_value='{"transaction": "abc", "requestId": "req-1"}',
    )
    def test_enabled_reaches_ultra_tools(self, mock_get_order, mock_execute):
        with patch.dict(
            os.environ,
            {"AUTOHEDGE_ENABLE_LIVE_TRADING": "I_UNDERSTAND_THIS_IS_REAL_MONEY"},
        ):
            result = execute_live_swap("mintA", "mintB", "1000")
        mock_get_order.assert_called_once_with("mintA", "mintB", "1000")
        mock_execute.assert_called_once_with("abc", "req-1")
        self.assertIn("Success", result)


if __name__ == "__main__":
    unittest.main()
