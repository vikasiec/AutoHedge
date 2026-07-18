"""
Paper trading ledger.

Tracks cash, open positions, and trade history in a JSON file so runs are
persistent across CLI sessions. No network or exchange access happens here;
fills are recorded at a price the caller supplies (normally the live quote
fetched right before executing).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from autohedge.schemas import ExecutionOrder, TradeFill

DEFAULT_STARTING_CASH = 100_000.0


@dataclass
class Position:
    ticker: str
    quantity: float
    avg_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    last_price: float = 0.0

    def market_value(self) -> float:
        return self.quantity * (self.last_price or self.avg_price)

    def unrealized_pnl(self) -> float:
        if not self.last_price:
            return 0.0
        return (self.last_price - self.avg_price) * self.quantity


class PaperPortfolio:
    def __init__(
        self,
        path: str | Path = "outputs/portfolio.json",
        starting_cash: float = DEFAULT_STARTING_CASH,
    ):
        self.path = Path(path)
        self.starting_cash = starting_cash
        self.cash: float = starting_cash
        self.positions: dict[str, Position] = {}
        self.history: list[dict] = []
        self._start_of_day_equity: float = starting_cash
        self._trading_day: str = date.today().isoformat()
        self._load()

    # -- persistence -----------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            self._save()
            return
        data = json.loads(self.path.read_text())
        self.cash = data.get("cash", self.starting_cash)
        self.positions = {
            t: Position(**p) for t, p in data.get("positions", {}).items()
        }
        self.history = data.get("history", [])
        self._start_of_day_equity = data.get(
            "start_of_day_equity", self.starting_cash
        )
        self._trading_day = data.get(
            "trading_day", date.today().isoformat()
        )
        self._roll_day_if_needed()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "cash": self.cash,
            "positions": {t: asdict(p) for t, p in self.positions.items()},
            "history": self.history,
            "start_of_day_equity": self._start_of_day_equity,
            "trading_day": self._trading_day,
        }
        self.path.write_text(json.dumps(data, indent=2))

    def _roll_day_if_needed(self) -> None:
        today = date.today().isoformat()
        if today != self._trading_day:
            self._trading_day = today
            self._start_of_day_equity = self.total_equity()
            self._save()

    # -- valuation ---------------------------------------------------------

    def has_position(self, ticker: str) -> bool:
        return ticker in self.positions

    def update_price(self, ticker: str, price: float) -> None:
        if ticker in self.positions:
            self.positions[ticker].last_price = price

    def total_exposure_usd(self) -> float:
        return sum(p.market_value() for p in self.positions.values())

    def total_equity(self) -> float:
        return self.cash + self.total_exposure_usd()

    def start_of_day_equity(self) -> float:
        self._roll_day_if_needed()
        return self._start_of_day_equity

    def daily_pnl(self) -> float:
        return self.total_equity() - self.start_of_day_equity()

    # -- trading -------------------------------------------------------

    def fill(self, order: ExecutionOrder, fill_price: float) -> TradeFill:
        """Record a paper fill at `fill_price` and persist the ledger."""
        self._roll_day_if_needed()
        notional = order.quantity * fill_price

        if order.side == "buy":
            if notional > self.cash:
                raise ValueError(
                    f"insufficient paper cash: need {notional:.2f}, have {self.cash:.2f}"
                )
            self.cash -= notional
            pos = self.positions.get(order.ticker)
            if pos:
                total_qty = pos.quantity + order.quantity
                pos.avg_price = (
                    pos.avg_price * pos.quantity + fill_price * order.quantity
                ) / total_qty
                pos.quantity = total_qty
                pos.stop_loss = order.stop_loss
                pos.take_profit = order.take_profit
            else:
                pos = Position(
                    ticker=order.ticker,
                    quantity=order.quantity,
                    avg_price=fill_price,
                    stop_loss=order.stop_loss,
                    take_profit=order.take_profit,
                    last_price=fill_price,
                )
                self.positions[order.ticker] = pos
            pos.last_price = fill_price
        else:  # sell / close
            pos = self.positions.get(order.ticker)
            if not pos or pos.quantity < order.quantity:
                raise ValueError(
                    f"cannot sell {order.quantity} {order.ticker}: no matching open position"
                )
            self.cash += notional
            pos.quantity -= order.quantity
            pos.last_price = fill_price
            if pos.quantity <= 1e-9:
                del self.positions[order.ticker]

        trade = TradeFill(
            ticker=order.ticker,
            side=order.side,
            quantity=order.quantity,
            fill_price=fill_price,
            timestamp=datetime.now(timezone.utc).isoformat(),
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            mode="paper",
        )
        self.history.append(trade.model_dump())
        self._save()
        return trade
