"""
Deterministic risk management.

This replaces the old "Risk Manager" LLM agent, which only ever produced
risk *commentary* in free text and enforced nothing. Every number here is
computed in code from the actual portfolio state; an LLM is never in this
loop and cannot override it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from autohedge.portfolio import PaperPortfolio
from autohedge.schemas import QuantAnalysis, RiskDecision, Thesis


@dataclass
class RiskLimits:
    """All limits are enforced in code. Defaults are conservative."""

    max_position_pct: float = 0.10
    """Max fraction of total equity allocated to a single new position."""

    max_total_exposure_pct: float = 0.60
    """Max fraction of total equity allowed in open positions at once."""

    max_open_positions: int = 5

    daily_loss_limit_pct: float = 0.03
    """If realized+unrealized P&L today drops this far below start-of-day
    equity, no new positions are approved until the next trading day."""

    min_probability_score: float = 0.55
    """Quant agent's probability_score must clear this bar."""

    stop_loss_pct: float = 0.05
    """Fallback stop distance when quant key_levels don't bound the price."""

    take_profit_pct: float = 0.10
    """Fallback take-profit distance when key_levels don't bound the price."""


class RiskEngine:
    def __init__(self, limits: RiskLimits | None = None):
        self.limits = limits or RiskLimits()

    def evaluate(
        self,
        thesis: Thesis,
        quant: QuantAnalysis,
        portfolio: PaperPortfolio,
    ) -> RiskDecision:
        reasons: list[str] = []
        equity = portfolio.total_equity()

        if portfolio.daily_pnl() <= -self.limits.daily_loss_limit_pct * portfolio.start_of_day_equity():
            return RiskDecision(
                ticker=thesis.ticker,
                approved=False,
                reasons=[
                    "daily loss limit reached; no new positions until next trading day"
                ],
                position_size_usd=0.0,
                max_position_size_usd=0.0,
            )

        already_open = portfolio.has_position(thesis.ticker)
        if (
            not already_open
            and len(portfolio.positions) >= self.limits.max_open_positions
        ):
            reasons.append(
                f"max open positions ({self.limits.max_open_positions}) reached"
            )

        if quant.probability_score < self.limits.min_probability_score:
            reasons.append(
                f"probability_score {quant.probability_score:.2f} below minimum "
                f"{self.limits.min_probability_score:.2f}"
            )

        current_exposure = portfolio.total_exposure_usd()
        max_exposure_usd = self.limits.max_total_exposure_pct * equity
        headroom_usd = max(0.0, max_exposure_usd - current_exposure)

        max_position_size_usd = min(
            self.limits.max_position_pct * equity, headroom_usd
        )

        if max_position_size_usd <= 0:
            reasons.append("no exposure headroom remaining under risk limits")

        position_size_usd = 0.0 if reasons else max_position_size_usd

        stop_loss_price, take_profit_price = self._levels(thesis, quant)

        return RiskDecision(
            ticker=thesis.ticker,
            approved=not reasons,
            reasons=reasons,
            position_size_usd=round(position_size_usd, 2),
            max_position_size_usd=round(max_position_size_usd, 2),
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
        )

    def _levels(
        self, thesis: Thesis, quant: QuantAnalysis
    ) -> tuple[float, float]:
        price = quant.current_price
        support = quant.key_levels.support
        resistance = quant.key_levels.resistance

        if thesis.direction == "long":
            stop = support if 0 < support < price else price * (
                1 - self.limits.stop_loss_pct
            )
            take = resistance if resistance > price else price * (
                1 + self.limits.take_profit_pct
            )
        else:
            stop = resistance if resistance > price else price * (
                1 + self.limits.stop_loss_pct
            )
            take = support if 0 < support < price else price * (
                1 - self.limits.take_profit_pct
            )

        return round(stop, 6), round(take, 6)
