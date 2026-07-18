"""
AutoHedge agents: one LLM agent per pipeline stage.

Each agent is called explicitly, in order, by autohedge.main.AutoHedge —
there is no implicit `handoffs`-based orchestration here. That keeps the
control flow (and the risk gate between quant analysis and execution)
in plain, testable Python rather than inside the LLM framework's own
routing.
"""

from datetime import datetime

from swarms import Agent

from autohedge.prompts import (
    DIRECTOR_TICKER_DISCOVERY_PROMPT,
    DIRECTOR_PROMPT,
    EXECUTION_PROMPT,
    QUANT_PROMPT,
    RISK_PROMPT,
    SENTIMENT_PROMPT,
)
from autohedge.tools.exa_search_tool import exa_search
from autohedge.tools.yahoo_api import get_all_stock_data

_NOW = datetime.now()
# Exact date and time for all agent system prompts (simple, single line)
_DATE_TIME_LINE = _NOW.strftime("%A, %B %d, %Y at %H:%M")
if _NOW.tzinfo:
    _DATE_TIME_LINE += f" {_NOW.tzname() or ''}"
_SYSTEM_SUFFIX = f"\n\nCurrent date and time (use this as now): {_DATE_TIME_LINE.strip()}"

_JSON_ONLY_SUFFIX = (
    "\n\nRespond with ONLY a single JSON object matching the requested "
    "schema. No markdown fences, no commentary before or after the JSON."
)

sentiment_agent = Agent(
    agent_name="Sentiment-Agent",
    system_prompt=SENTIMENT_PROMPT + _SYSTEM_SUFFIX,
    model_name="gpt-4o-mini",
    verbose=True,
    max_loops=1,
    tools=[exa_search],
)

director_agent = Agent(
    agent_name="Trading-Director",
    system_prompt=DIRECTOR_PROMPT + _SYSTEM_SUFFIX + _JSON_ONLY_SUFFIX,
    model_name="gpt-4.1",
    max_loops=1,
    tools=[exa_search],
)

ticker_discovery_agent = Agent(
    agent_name="Ticker-Discovery",
    system_prompt=DIRECTOR_TICKER_DISCOVERY_PROMPT + _SYSTEM_SUFFIX,
    model_name="gpt-4.1",
    max_loops=1,
)

quant_agent = Agent(
    agent_name="Quant-Analyst",
    system_prompt=QUANT_PROMPT + _SYSTEM_SUFFIX + _JSON_ONLY_SUFFIX,
    model_name="gpt-4.1",
    output_type="str",
    max_loops=1,
    verbose=True,
    context_length=16000,
    tools=[get_all_stock_data],
)

execution_agent = Agent(
    agent_name="Execution-Agent",
    system_prompt=EXECUTION_PROMPT + _SYSTEM_SUFFIX + _JSON_ONLY_SUFFIX,
    model_name="gpt-4.1",
    output_type="str",
    max_loops=1,
    verbose=True,
    context_length=16000,
)

# Kept for reference / manual use; the deterministic RiskEngine
# (autohedge/risk_engine.py) is what actually gates trades now.
risk_agent = Agent(
    agent_name="Risk-Manager",
    system_prompt=RISK_PROMPT + _SYSTEM_SUFFIX,
    model_name="gpt-4.1",
    output_type="str",
    max_loops=1,
    verbose=True,
    context_length=16000,
)

ALL_AGENTS = [
    sentiment_agent,
    director_agent,
    ticker_discovery_agent,
    quant_agent,
    execution_agent,
    risk_agent,
]
