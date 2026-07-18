"""
Live Solana execution — explicit opt-in only.

AutoHedge.run() (autohedge/main.py) NEVER calls anything in this module.
It only drives the paper-trading pipeline: a simulated fill in
PaperPortfolio at a real fetched price, nothing more.

The functions in autohedge/tools/ultra_tools.py (get_order, execute_trade,
get_holdings) are real: execute_trade signs a transaction with your
SOLANA_PRIVATE_KEY and submits it to Jupiter for on-chain execution. That
is why they are gated here behind an explicit, deliberately unwieldy
confirmation instead of being wired into any agent automatically.

To place a real swap, call `execute_live_swap` directly yourself with
AUTOHEDGE_ENABLE_LIVE_TRADING=I_UNDERSTAND_THIS_IS_REAL_MONEY set in your
environment. There is no other path to real execution in this codebase.
"""

import json
import os

from loguru import logger

from autohedge.tools.ultra_tools import execute_trade, get_order

_CONFIRMATION_VALUE = "I_UNDERSTAND_THIS_IS_REAL_MONEY"


class LiveTradingDisabledError(RuntimeError):
    pass


def _require_live_trading_enabled() -> None:
    if os.getenv("AUTOHEDGE_ENABLE_LIVE_TRADING") != _CONFIRMATION_VALUE:
        raise LiveTradingDisabledError(
            "Live trading is disabled. This would sign a real transaction "
            "with SOLANA_PRIVATE_KEY and submit it on-chain. To proceed, "
            "set AUTOHEDGE_ENABLE_LIVE_TRADING="
            f"{_CONFIRMATION_VALUE} in your environment and call this "
            "function directly yourself."
        )


def execute_live_swap(
    input_mint: str, output_mint: str, amount: str
) -> str:
    """
    Request a swap order and immediately sign + execute it for real.

    Raises LiveTradingDisabledError unless AUTOHEDGE_ENABLE_LIVE_TRADING
    is explicitly set. This is intentionally not called from anywhere
    else in the codebase.
    """
    _require_live_trading_enabled()
    logger.warning(
        "LIVE TRADE: swapping {} of {} -> {} on-chain",
        amount,
        input_mint,
        output_mint,
    )
    order_json = get_order(input_mint, output_mint, amount)
    order = json.loads(order_json)
    return execute_trade(order["transaction"], order["requestId"])
