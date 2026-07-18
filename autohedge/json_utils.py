"""
Helpers for getting validated structured output out of swarms Agents.

Agents are prompted to reply with a single JSON object, but LLMs
sometimes wrap it in markdown fences or add stray commentary. This module
extracts the JSON, validates it against a pydantic model, and retries
once (feeding the validation error back to the agent) before giving up.
"""

from __future__ import annotations

import json
import re
from typing import Type, TypeVar

from loguru import logger
from pydantic import BaseModel, ValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)

_JSON_BLOCK_RE = re.compile(r"\{.*\}|\[.*\]", re.DOTALL)


class JsonParseError(RuntimeError):
    pass


def extract_json(text: str) -> dict | list:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = _JSON_BLOCK_RE.search(text)
    if not match:
        raise JsonParseError(f"no JSON object/array found in: {text[:300]!r}")
    try:
        return json.loads(match.group(0))
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
