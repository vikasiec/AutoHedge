import json
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from autohedge.json_utils import JsonParseError, extract_json, run_agent_json
from autohedge.portfolio import PaperPortfolio
from autohedge.risk_engine import RiskEngine, RiskLimits
from autohedge.schemas import (
    ExecutionOrder,
    QuantAnalysis,
    RiskDecision,
    Thesis,
)
from autohedge.tools.yahoo_api import get_last_price
from autohedge.workers import (
    director_agent,
    execution_agent,
    quant_agent,
    ticker_discovery_agent,
)
from autohedge.prompts import (
    DIRECTOR_THESIS_PROMPT,
    EXECUTION_ORDER_PROMPT,
    QUANT_ANALYSIS_PROMPT,
)

_PRICE_TOLERANCE = 0.02  # allow 2% drift between quant's quote and a fresh fetch


class AutoHedge:
    """
    Paper-trading research pipeline: Director (thesis) -> Quant (grounded
    in real market data) -> RiskEngine (deterministic gate) -> Execution
    -> PaperPortfolio fill.

    Every trade is simulated against a local JSON ledger at a real market
    price; nothing here signs or submits a real transaction. See
    autohedge/tools/ultra_tools.py for the (separate, opt-in) live Solana
    execution path.
    """

    def __init__(
        self,
        name: str = "autohedge",
        output_dir: str = "outputs",
        portfolio_path: str = "outputs/portfolio.json",
        starting_cash: float = 100_000.0,
        risk_limits: RiskLimits | None = None,
    ):
        self.name = name
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

        self.portfolio = PaperPortfolio(
            path=portfolio_path, starting_cash=starting_cash
        )
        self.risk_engine = RiskEngine(risk_limits)

        logger.info("AutoHedge initialized (paper trading mode)")

    def discover_tickers(self, task: str) -> list[str]:
        raw = ticker_discovery_agent.run(task=task)
        try:
            tickers = extract_json(str(raw))
        except JsonParseError as e:
            logger.error("Ticker discovery failed to parse: {}", e)
            return []
        if not isinstance(tickers, list):
            logger.error("Ticker discovery did not return a list: {}", tickers)
            return []
        return [str(t).strip().upper() for t in tickers if str(t).strip()]

    def _run_cycle_for_ticker(self, task: str, ticker: str) -> dict:
        result: dict = {"ticker": ticker}

        try:
            thesis = run_agent_json(
                director_agent,
                DIRECTOR_THESIS_PROMPT.format(task=task, stock=ticker),
                Thesis,
            )
            thesis.ticker = ticker
        except JsonParseError as e:
            result["error"] = f"thesis generation failed: {e}"
            return result
        result["thesis"] = thesis.model_dump()

        try:
            quant = run_agent_json(
                quant_agent,
                QUANT_ANALYSIS_PROMPT.format(
                    stock=ticker, thesis=thesis.summary
                ),
                QuantAnalysis,
            )
            quant.ticker = ticker
        except JsonParseError as e:
            result["error"] = f"quant analysis failed: {e}"
            return result

        try:
            real_price = get_last_price(ticker)
            drift = abs(real_price - quant.current_price) / real_price
            if drift > _PRICE_TOLERANCE:
                logger.warning(
                    "{}: quant current_price {} drifted {:.1%} from live "
                    "price {}; using live price",
                    ticker,
                    quant.current_price,
                    drift,
                    real_price,
                )
            quant.current_price = real_price
        except Exception as e:
            result["error"] = f"could not fetch live price: {e}"
            return result
        result["quant"] = quant.model_dump()

        self.portfolio.update_price(ticker, quant.current_price)
        risk_decision = self.risk_engine.evaluate(
            thesis, quant, self.portfolio
        )
        result["risk_decision"] = risk_decision.model_dump()

        if not risk_decision.approved:
            result["status"] = "rejected"
            return result

        try:
            order = run_agent_json(
                execution_agent,
                EXECUTION_ORDER_PROMPT.format(
                    stock=ticker,
                    direction=thesis.direction,
                    risk_decision=risk_decision.model_dump_json(),
                ),
                ExecutionOrder,
            )
            order.ticker = ticker
        except JsonParseError as e:
            result["error"] = f"execution order generation failed: {e}"
            return result

        violation = self._validate_order_against_risk(
            order, thesis, risk_decision, quant.current_price
        )
        if violation:
            result["error"] = f"execution order rejected: {violation}"
            return result
        result["order"] = order.model_dump()

        try:
            fill = self.portfolio.fill(order, fill_price=quant.current_price)
        except ValueError as e:
            result["error"] = f"paper fill failed: {e}"
            return result

        result["fill"] = fill.model_dump()
        result["status"] = "filled"
        return result

    @staticmethod
    def _validate_order_against_risk(
        order: ExecutionOrder,
        thesis: Thesis,
        risk_decision: RiskDecision,
        current_price: float,
    ) -> str | None:
        """Defense-in-depth: never trust the execution agent's numbers
        blindly, even though the prompt tells it to stay within bounds."""
        expected_side = "buy" if thesis.direction == "long" else "sell"
        if order.side != expected_side:
            return f"side {order.side!r} does not match thesis direction {thesis.direction!r}"

        notional = order.quantity * current_price
        if notional > risk_decision.position_size_usd * 1.05:
            return (
                f"order notional {notional:.2f} exceeds approved position "
                f"size {risk_decision.position_size_usd:.2f}"
            )
        return None

    def run(self, task: str) -> list[dict]:
        logger.info("Starting trading cycle: {}", task)
        tickers = self.discover_tickers(task)
        if not tickers:
            logger.warning("No tickers discovered for task: {}", task)
            return []

        results = [
            self._run_cycle_for_ticker(task, ticker) for ticker in tickers
        ]

        run_file = self.output_dir / (
            f"run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        run_file.write_text(json.dumps(results, indent=2, default=str))
        return results
