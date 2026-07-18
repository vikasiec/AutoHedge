"""
AutoHedge dashboard (Streamlit).

Run with: streamlit run ui/app.py

Paper trading (Run Pipeline / Portfolio / History) is always available.
The Live Trading tab is a thin, heavily-gated front end over
autohedge/live.py -- it never bypasses that module's own safety check,
and it cannot itself set AUTOHEDGE_ENABLE_LIVE_TRADING; that must
already be set in the environment the Streamlit process was launched
with.
"""

import json
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autohedge.env_loader import load_env

load_env()

from autohedge import AutoHedge
from autohedge.live import (
    LiveTradingDisabledError,
    execute_live_swap,
    get_wallet_address,
    get_wallet_holdings,
    is_live_trading_enabled,
)
from autohedge.portfolio import PaperPortfolio
from autohedge.risk_engine import RiskLimits
from autohedge.workers import LIGHT_MODEL_NAME, MODEL_NAME

PORTFOLIO_PATH = "outputs/portfolio.json"
OUTPUT_DIR = "outputs"

st.set_page_config(page_title="AutoHedge", layout="wide")


def load_portfolio() -> PaperPortfolio:
    return PaperPortfolio(path=PORTFOLIO_PATH)


def render_sidebar() -> None:
    st.sidebar.title("AutoHedge")
    st.sidebar.caption("Paper-trading research pipeline")

    st.sidebar.subheader("LLM Config")
    st.sidebar.text(f"Model: {MODEL_NAME}")
    st.sidebar.text(f"Light model: {LIGHT_MODEL_NAME}")
    st.sidebar.text(f"OPENAI_API_KEY set: {bool(os.getenv('OPENAI_API_KEY'))}")
    st.sidebar.text(f"GEMINI_API_KEY set: {bool(os.getenv('GEMINI_API_KEY'))}")

    st.sidebar.subheader("Risk Limits (default)")
    limits = RiskLimits()
    st.sidebar.text(f"Max position: {limits.max_position_pct:.0%} of equity")
    st.sidebar.text(f"Max exposure: {limits.max_total_exposure_pct:.0%} of equity")
    st.sidebar.text(f"Max open positions: {limits.max_open_positions}")
    st.sidebar.text(f"Daily loss limit: {limits.daily_loss_limit_pct:.0%}")
    st.sidebar.text(f"Min probability score: {limits.min_probability_score:.2f}")


def render_run_tab() -> None:
    st.header("Run a Pipeline Cycle")
    st.caption(
        "Calls the Director / Quant / Execution agents for real -- this "
        "uses your LLM API key's quota. Trades are simulated (paper) "
        "against outputs/portfolio.json; nothing here signs a real "
        "transaction."
    )

    task = st.text_area(
        "Task",
        value="Analyze NVDA for a swing trade",
        help="Natural-language task; the Director agent figures out which "
        "tickers are relevant.",
    )
    starting_cash = st.number_input(
        "Starting cash (only applies the first time a portfolio is created)",
        min_value=1000.0,
        value=100_000.0,
        step=1000.0,
    )

    if st.button("Run Cycle", type="primary"):
        with st.spinner("Running Director -> Quant -> Risk -> Execution..."):
            try:
                system = AutoHedge(
                    output_dir=OUTPUT_DIR,
                    portfolio_path=PORTFOLIO_PATH,
                    starting_cash=starting_cash,
                )
                results = system.run(task)
            except Exception as e:
                st.error(f"Run failed: {e}")
                return

        if not results:
            st.warning("No tickers were discovered for this task.")
            return

        for r in results:
            ticker = r.get("ticker", "?")
            status = r.get("status", r.get("error", "unknown"))
            with st.expander(f"{ticker} -- {status}", expanded=True):
                if "error" in r:
                    st.error(r["error"])
                if "thesis" in r:
                    st.subheader("Thesis")
                    st.json(r["thesis"])
                if "quant" in r:
                    st.subheader("Quant Analysis")
                    st.json(r["quant"])
                if "risk_decision" in r:
                    st.subheader("Risk Decision")
                    rd = r["risk_decision"]
                    if rd.get("approved"):
                        st.success(
                            f"Approved -- position size ${rd['position_size_usd']:,.2f}"
                        )
                    else:
                        st.warning(f"Rejected: {', '.join(rd.get('reasons', []))}")
                    st.json(rd)
                if "order" in r:
                    st.subheader("Execution Order")
                    st.json(r["order"])
                if "fill" in r:
                    st.subheader("Fill")
                    st.json(r["fill"])


def render_portfolio_tab() -> None:
    st.header("Paper Portfolio")
    pf = load_portfolio()

    col1, col2, col3 = st.columns(3)
    col1.metric("Cash", f"${pf.cash:,.2f}")
    col2.metric("Equity", f"${pf.total_equity():,.2f}")
    col3.metric("Today's P&L", f"${pf.daily_pnl():+,.2f}")

    st.subheader("Open Positions")
    if not pf.positions:
        st.info("No open positions.")
    else:
        rows = [
            {
                "Ticker": p.ticker,
                "Qty": p.quantity,
                "Avg Price": p.avg_price,
                "Last Price": p.last_price,
                "Market Value": p.market_value(),
                "Unrealized P&L": p.unrealized_pnl(),
            }
            for p in pf.positions.values()
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True)

    with st.expander("Reset paper portfolio (starts over with fresh cash)"):
        reset_cash = st.number_input(
            "New starting cash", min_value=1000.0, value=100_000.0, step=1000.0
        )
        if st.button("Reset Portfolio", type="secondary"):
            Path(PORTFOLIO_PATH).unlink(missing_ok=True)
            PaperPortfolio(path=PORTFOLIO_PATH, starting_cash=reset_cash)
            st.success("Portfolio reset.")
            st.rerun()


def render_history_tab() -> None:
    st.header("Trade History")
    pf = load_portfolio()

    if not pf.history:
        st.info("No trades yet.")
        return

    df = pd.DataFrame(pf.history)
    st.dataframe(df, use_container_width=True)

    st.subheader("Past Run Logs")
    out_dir = Path(OUTPUT_DIR)
    run_files = sorted(out_dir.glob("run_*.json"), reverse=True) if out_dir.exists() else []
    if not run_files:
        st.info("No run logs yet.")
        return
    selected = st.selectbox("Select a run", [f.name for f in run_files])
    if selected:
        content = json.loads((out_dir / selected).read_text())
        st.json(content)


def render_live_trading_tab() -> None:
    st.header("Live Trading -- Real Money, Real Solana Transactions")
    st.error(
        "This executes a real, signed, on-chain swap using SOLANA_PRIVATE_KEY. "
        "It is not simulated. Nothing here is reversible once submitted."
    )

    if not is_live_trading_enabled():
        st.warning(
            "Live trading is disabled. This panel cannot enable it. To use "
            "it, stop this app, set AUTOHEDGE_ENABLE_LIVE_TRADING="
            "I_UNDERSTAND_THIS_IS_REAL_MONEY in the environment the "
            "Streamlit server is launched from, and restart."
        )
        return

    try:
        address = get_wallet_address()
    except Exception as e:
        st.error(f"Could not load wallet: {e}")
        return

    st.text(f"Wallet address: {address}")

    if st.button("Refresh holdings"):
        try:
            holdings = json.loads(get_wallet_holdings())
            st.json(holdings)
        except Exception as e:
            st.error(f"Could not fetch holdings: {e}")

    st.divider()
    st.subheader("Submit a swap")
    st.caption(
        "Mint addresses, not tickers. Example: SOL = "
        "So11111111111111111111111111111111111111112, "
        "USDC = EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    )

    input_mint = st.text_input("Input mint")
    output_mint = st.text_input("Output mint")
    amount = st.text_input("Amount (smallest units, e.g. lamports for SOL)")

    st.warning(
        "Double-check the amount's unit. This is NOT a human-readable "
        "quantity -- e.g. 1 SOL = 1000000000 (1e9 lamports)."
    )

    confirm_text = st.text_input(
        'Type exactly "CONFIRM LIVE TRADE" to arm the button below'
    )
    armed = confirm_text.strip() == "CONFIRM LIVE TRADE"

    if st.button(
        "Execute Live Trade",
        type="primary",
        disabled=not (armed and input_mint and output_mint and amount),
    ):
        with st.spinner("Signing and submitting on-chain..."):
            try:
                result = execute_live_swap(input_mint, output_mint, amount)
                st.success("Submitted.")
                st.json(json.loads(result))
            except LiveTradingDisabledError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"Live trade failed: {e}")


def main() -> None:
    render_sidebar()
    tabs = st.tabs(
        ["Run Pipeline", "Portfolio", "History", "Live Trading (danger)"]
    )
    with tabs[0]:
        render_run_tab()
    with tabs[1]:
        render_portfolio_tab()
    with tabs[2]:
        render_history_tab()
    with tabs[3]:
        render_live_trading_tab()


if __name__ == "__main__":
    main()
