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

The only two ways to reach `execute_live_swap`:
  1. Call it directly yourself in Python with
     AUTOHEDGE_ENABLE_LIVE_TRADING=I_UNDERSTAND_THIS_IS_REAL_MONEY set.
  2. The Live Trading tab in ui/app.py -- which itself only renders as
     usable when that same env var is already set in the process the
     Streamlit server was launched with. The UI cannot set that variable
     for you; it can only use it if it's already there. On top of that,
     the UI requires a typed confirmation phrase before the trade button
     is enabled at all. Neither path bypasses `_require_live_trading_enabled`.
"""

import json
import os

from loguru import logger

from autohedge.tools.ultra_tools import execute_trade, get_holdings, get_order

_CONFIRMATION_VALUE = "I_UNDERSTAND_THIS_IS_REAL_MONEY"


class LiveTradingDisabledError(RuntimeError):
    pass


def is_live_trading_enabled() -> bool:
    """Non-raising check, safe for a UI to poll before rendering controls."""
    return os.getenv("AUTOHEDGE_ENABLE_LIVE_TRADING") == _CONFIRMATION_VALUE


def _require_live_trading_enabled() -> None:
    if not is_live_trading_enabled():
        raise LiveTradingDisabledError(
            "Live trading is disabled. This would sign a real transaction "
            "with SOLANA_PRIVATE_KEY and submit it on-chain. To proceed, "
            "set AUTOHEDGE_ENABLE_LIVE_TRADING="
            f"{_CONFIRMATION_VALUE} in your environment and call this "
            "function directly yourself."
        )


def get_wallet_address() -> str:
    """
    Return the wallet's public key (safe to display -- it's public by
    definition). Does not require live trading to be enabled, since
    merely showing an address signs nothing.

    Raises ValueError if SOLANA_PRIVATE_KEY is not set/invalid.
    """
    from autohedge.tools.ultra_tools import _get_wallet_pubkey

    return _get_wallet_pubkey()


def get_wallet_holdings() -> str:
    """Read-only: current token/SOL balances for the configured wallet."""
    return get_holdings(get_wallet_address())


def execute_live_swap(
    input_mint: str, output_mint: str, amount: str
) -> str:
    """
    Request a swap order and immediately sign + execute it for real.

    Raises LiveTradingDisabledError unless AUTOHEDGE_ENABLE_LIVE_TRADING
    is explicitly set.
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
