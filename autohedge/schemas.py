"""
Structured data models passed between pipeline stages.

Agents are prompted to return JSON matching these schemas so that the
orchestrator (see main.py) can parse, validate, and act on their output in
code, instead of passing free-form text between stages and hoping the next
agent interprets it correctly.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class KeyLevels(BaseModel):
    support: float
    resistance: float
    pivot: float


class Thesis(BaseModel):
    """Output of the Director agent for a single ticker."""

    ticker: str
    direction: Literal["long", "short"]
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    key_factors: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class QuantAnalysis(BaseModel):
    """Output of the Quant agent for a single ticker."""

    ticker: str
    technical_score: float = Field(ge=0.0, le=1.0)
    volume_score: float = Field(ge=0.0, le=1.0)
    trend_strength: float = Field(ge=0.0, le=1.0)
    volatility: float = Field(ge=0.0)
    probability_score: float = Field(ge=0.0, le=1.0)
    key_levels: KeyLevels
    current_price: float = Field(gt=0.0)


class RiskDecision(BaseModel):
    """
    Output of the deterministic RiskEngine (code, not an LLM) for a
    proposed trade. `approved=False` must halt execution for this ticker.
    """

    ticker: str
    approved: bool
    reasons: list[str] = Field(default_factory=list)
    position_size_usd: float = Field(ge=0.0)
    max_position_size_usd: float = Field(ge=0.0)
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None


class ExecutionOrder(BaseModel):
    """Output of the Execution agent, gated by an approved RiskDecision."""

    ticker: str
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit"] = "market"
    quantity: float = Field(gt=0.0)
    entry_price: float = Field(gt=0.0)
    stop_loss: float = Field(gt=0.0)
    take_profit: float = Field(gt=0.0)
    time_in_force: str = "day"

    @field_validator("quantity")
    @classmethod
    def _quantity_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("quantity must be positive")
        return v


class TradeFill(BaseModel):
    """Result of a paper (or live) execution, recorded in the ledger."""

    ticker: str
    side: Literal["buy", "sell"]
    quantity: float
    fill_price: float
    timestamp: str
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    mode: Literal["paper", "live"] = "paper"
