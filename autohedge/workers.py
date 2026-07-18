"""
AutoHedge agents: one LLM agent per pipeline stage.

Each agent is called explicitly, in order, by autohedge.main.AutoHedge —
there is no implicit `handoffs`-based orchestration here. That keeps the
control flow (and the risk gate between quant analysis and execution)
in plain, testable Python rather than inside the LLM framework's own
routing.
"""

import os
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

# All agents run through swarms -> LiteLLM, which routes by model name
# prefix (e.g. "gpt-*" -> OpenAI via OPENAI_API_KEY, "gemini/*" -> Gemini
# via GEMINI_API_KEY). Set AUTOHEDGE_MODEL to switch providers without
# touching agent definitions.
MODEL_NAME = os.getenv("AUTOHEDGE_MODEL") or "gpt-4.1"
LIGHT_MODEL_NAME = os.getenv("AUTOHEDGE_LIGHT_MODEL") or "gpt-4o-mini"

# "Thinking" models (e.g. Gemini 2.5+/3.x) spend part of max_tokens on
# internal reasoning before emitting visible text. The swarms default
# (4096) can be entirely consumed by reasoning on these models, leaving
# no budget for the actual answer. Give every agent headroom for both.
MAX_TOKENS = int(os.getenv("AUTOHEDGE_MAX_TOKENS", "8192"))

# swarms Agent.run() defaults to output_type="str-all-except-first",
# which returns most of the conversation history as one string -- not
# just the model's final answer. Every JSON-output agent below sets
# output_type="final" explicitly so .run() returns only the last
# message, which is what json_utils.run_agent_json expects to parse.

# NOTE on `tools=`: swarms.Agent has two confirmed bugs that make its
# tool-calling path unsafe for our single-shot, JSON-output agents:
#   1. `tools_list_dictionary` defaults to a mutable `[]` in Agent.__init__
#      (swarms/structs/agent.py), so tool schemas from one agent leak into
#      every later Agent that doesn't pass its own tools_list_dictionary.
#   2. LiteLLMWrapper.output_for_tools() unconditionally returns
#      response.choices[0].message.tool_calls, which is None whenever the
#      model answers in plain text instead of calling a tool -- it never
#      falls back to the actual text content, silently discarding a valid
#      answer.
# We work around (1) by passing tools_list_dictionary=None explicitly on
# every agent (forces a fresh list per instance instead of sharing the
# buggy default), and work around (2) by not giving the JSON-output
# agents (director/ticker-discovery/quant/execution/risk) any tools at
# all -- real market data is fetched deterministically in main.py and
# embedded directly in the prompt instead of left to the model's
# tool-calling judgment.

sentiment_agent = Agent(
    agent_name="Sentiment-Agent",
    system_prompt=SENTIMENT_PROMPT + _SYSTEM_SUFFIX,
    model_name=LIGHT_MODEL_NAME,
    verbose=True,
    max_loops=1,
    max_tokens=MAX_TOKENS,
    tools=[exa_search],
    tools_list_dictionary=None,
)

director_agent = Agent(
    agent_name="Trading-Director",
    system_prompt=DIRECTOR_PROMPT + _SYSTEM_SUFFIX + _JSON_ONLY_SUFFIX,
    model_name=MODEL_NAME,
    output_type="final",
    max_loops=1,
    max_tokens=MAX_TOKENS,
    tools_list_dictionary=None,
)

ticker_discovery_agent = Agent(
    agent_name="Ticker-Discovery",
    system_prompt=DIRECTOR_TICKER_DISCOVERY_PROMPT + _SYSTEM_SUFFIX,
    model_name=MODEL_NAME,
    output_type="final",
    max_loops=1,
    max_tokens=MAX_TOKENS,
    tools_list_dictionary=None,
)

quant_agent = Agent(
    agent_name="Quant-Analyst",
    system_prompt=QUANT_PROMPT + _SYSTEM_SUFFIX + _JSON_ONLY_SUFFIX,
    model_name=MODEL_NAME,
    output_type="final",
    max_loops=1,
    verbose=True,
    context_length=16000,
    max_tokens=MAX_TOKENS,
    tools_list_dictionary=None,
)

execution_agent = Agent(
    agent_name="Execution-Agent",
    system_prompt=EXECUTION_PROMPT + _SYSTEM_SUFFIX + _JSON_ONLY_SUFFIX,
    model_name=MODEL_NAME,
    output_type="final",
    max_loops=1,
    verbose=True,
    context_length=16000,
    max_tokens=MAX_TOKENS,
    tools_list_dictionary=None,
)

# Kept for reference / manual use; the deterministic RiskEngine
# (autohedge/risk_engine.py) is what actually gates trades now.
risk_agent = Agent(
    agent_name="Risk-Manager",
    system_prompt=RISK_PROMPT + _SYSTEM_SUFFIX,
    model_name=MODEL_NAME,
    output_type="final",
    max_loops=1,
    verbose=True,
    context_length=16000,
    max_tokens=MAX_TOKENS,
    tools_list_dictionary=None,
)

ALL_AGENTS = [
    sentiment_agent,
    director_agent,
    ticker_discovery_agent,
    quant_agent,
    execution_agent,
    risk_agent,
]
