"""
Helpers for getting validated structured output out of swarms Agents.

Agents are prompted to reply with a single JSON object, but LLMs
sometimes wrap it in markdown fences or add stray commentary. This module
extracts the JSON, validates it against a pydantic model, and retries
once (feeding the validation error back to the agent) before giving up.
"""

from __future__ import annotations

import json
from typing import Type, TypeVar

from loguru import logger
from pydantic import BaseModel, ValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)

_decoder = json.JSONDecoder()


class JsonParseError(RuntimeError):
    pass


def extract_json(text: str) -> dict | list:
    """
    Parse the first complete JSON value out of `text`, ignoring anything
    before or after it.

    LLMs sometimes wrap the JSON in markdown fences, add stray
    commentary, or -- particularly "thinking" models -- echo the same
    answer twice in one response. A naive `json.loads(text)` fails on
    all of these, and a greedy regex from the first `{` to the *last*
    `}` breaks specifically on the double-answer case (it spans both
    objects, producing invalid JSON). `JSONDecoder.raw_decode` parses
    exactly one JSON value starting at a given index and reports where
    it ended, so trailing content -- including a full duplicate object
    -- is simply ignored rather than corrupting the parse.
    """
    stripped = text.strip()
    start = next((i for i, ch in enumerate(stripped) if ch in "{["), None)
    if start is None:
        raise JsonParseError(f"no JSON object/array found in: {text[:300]!r}")

    try:
        value, _end = _decoder.raw_decode(stripped, start)
        return value
    except json.JSONDecodeError as e:
        raise JsonParseError(f"invalid JSON in agent response: {e}") from e


def run_agent_json(
    agent,
    prompt: str,
    model: Type[ModelT],
    max_retries: int = 1,
) -> ModelT:
    """
    Run `agent` on `prompt`, parse its response as JSON, and validate it
    against `model`. On parse/validation failure, ask the agent to correct
    itself (up to `max_retries` times) before raising.
    """
    last_error: Exception | None = None
    current_prompt = prompt

    for attempt in range(max_retries + 1):
        raw = agent.run(task=current_prompt)
        try:
            data = extract_json(str(raw))
            if not isinstance(data, dict):
                raise JsonParseError(
                    f"expected a JSON object for {model.__name__}, got {type(data).__name__}"
                )
            return model(**data)
        except (JsonParseError, ValidationError, TypeError) as e:
            last_error = e
            logger.warning(
                "{}: response failed validation against {} (attempt {}/{}): {}",
                agent.agent_name,
                model.__name__,
                attempt + 1,
                max_retries + 1,
                e,
            )
            current_prompt = (
                f"{prompt}\n\nYour previous reply was invalid: {e}\n"
                "Reply again with ONLY the corrected JSON object."
            )

    raise JsonParseError(
        f"{agent.agent_name} failed to produce valid {model.__name__} "
        f"after {max_retries + 1} attempts: {last_error}"
    )
