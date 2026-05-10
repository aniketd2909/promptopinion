"""Shared Google Gemini client and structured-completion helper.

A single ``google-genai`` client is created lazily on first use and reused for
the lifetime of the process so we don't re-build transport state on every tool
call. All LLM traffic flows through :func:`structured_completion`, which:

- Forces JSON-typed structured output via a Pydantic ``response_schema`` and
  returns a validated instance — no string-scraping in the callers.
- Retries on errors that are plausibly transient (HTTP 429 / 5xx) with
  exponential backoff. 4xx errors that won't get better on retry (invalid
  request, content blocked) are surfaced immediately.
- Caps each request with an ``asyncio`` timeout so a slow upstream can't pin
  an MCP request open indefinitely.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional, Type, TypeVar

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import BaseModel, ValidationError
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)


logger = logging.getLogger(__name__)


DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_TEMPERATURE = 0.1
DEFAULT_TIMEOUT_SECONDS = 60.0
MAX_RETRY_ATTEMPTS = 3


T = TypeVar("T", bound=BaseModel)


_client: Optional[genai.Client] = None


class LLMResponseError(RuntimeError):
    """Raised when Gemini returns no usable structured output.

    Distinct from ``genai_errors.APIError`` (transport / API-level failures)
    so callers can tell "the API said no" apart from "the API said yes but
    the content was unusable".
    """


def _get_client() -> genai.Client:
    global _client
    if _client is not None:
        return _client
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY is not set. The MCP server cannot reach Gemini."
        )
    _client = genai.Client(api_key=api_key)
    return _client


def _get_model() -> str:
    return os.getenv("GEMINI_MODEL", DEFAULT_MODEL)


def _is_retryable(exc: BaseException) -> bool:
    if not isinstance(exc, genai_errors.APIError):
        return False
    status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if status is None:
        return True
    return status == 429 or status >= 500


def _extract_finish_reason(response: object) -> str:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return "no-candidates"
    return str(getattr(candidates[0], "finish_reason", "unknown"))


@retry(
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)
async def structured_completion(
    *,
    system: str,
    user: str,
    schema: Type[T],
    temperature: float = DEFAULT_TEMPERATURE,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> T:
    """Call Gemini and parse its JSON response into ``schema``.

    Returns a validated Pydantic instance. Raises :class:`LLMResponseError`
    when the response is empty (safety filter, truncation) or fails schema
    validation, and ``genai_errors.APIError`` on terminal transport errors.
    """
    client = _get_client()
    model = _get_model()

    config = genai_types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        response_schema=schema,
        temperature=temperature,
    )

    response = await asyncio.wait_for(
        client.aio.models.generate_content(
            model=model,
            contents=user,
            config=config,
        ),
        timeout=timeout_seconds,
    )

    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, schema):
        return parsed
    if isinstance(parsed, dict):
        try:
            return schema.model_validate(parsed)
        except ValidationError as exc:
            raise LLMResponseError(
                f"Gemini response did not match {schema.__name__}: {exc}"
            ) from exc

    text = getattr(response, "text", None)
    if not text:
        raise LLMResponseError(
            f"Gemini returned no content (finish_reason="
            f"{_extract_finish_reason(response)}, model={model})."
        )

    try:
        return schema.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise LLMResponseError(
            f"Gemini response did not match {schema.__name__}: {exc}"
        ) from exc
