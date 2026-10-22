"""
LLM client wrapper.

The OpenAI SDK is imported only here. Nothing else in the codebase touches it.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Callable, Generic, List, Optional, Type, TypeVar

from django.conf import settings
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cost table — Ollama is free/local so cost is 0
# ---------------------------------------------------------------------------
_COST_PER_1K = {
    "gpt-4o-mini":  {"input": 0.000150, "output": 0.000600},
    "gpt-4o":       {"input": 0.002500, "output": 0.010000},
    "llama3.2":     {"input": 0.0, "output": 0.0},
}

_DEFAULT_MODEL = "llama3.2"
_DEFAULT_TIMEOUT = 120         # Ollama local inference can be slower
_MAX_RETRIES = 3
_BACKOFF_BASE = 2              # seconds; delay = base ** attempt


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class LLMMessage:
    role: str   # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    content: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    model: str


@dataclass
class StructuredResponse(Generic[T]):
    """Return value of LLMClient.extract_structured()."""
    result: Optional[T]          # None on permanent failure
    raw: str                     # last raw content from the model
    retried: bool                # True if a correction attempt was made
    failure_reason: Optional[str]  # set when result is None


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LLMError(Exception):
    """Unretryable error — bad request, auth failure, etc."""


class LLMRateLimitError(Exception):
    """Rate limit hit — caller may retry after backoff."""


class LLMServerError(Exception):
    """Transient server error — safe to retry."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class LLMClient:
    """
    Thin wrapper around the OpenAI chat completions API.

    Pass `_call_fn` in tests to inject a fake without any network call:

        client = LLMClient(_call_fn=lambda **kw: fake_response)
    """

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        timeout: int = _DEFAULT_TIMEOUT,
        _call_fn: Optional[Callable] = None,
    ):
        self.model = model
        self.timeout = timeout
        self._call_fn = _call_fn or self._real_call

    # ------------------------------------------------------------------
    # Structured output — parse + one self-correction retry
    # ------------------------------------------------------------------

    def extract_structured(
        self,
        messages: List[LLMMessage],
        schema: Type[T],
    ) -> StructuredResponse[T]:
        """
        Call the model, extract JSON from the response, validate against
        `schema` (a Pydantic model), and on failure retry exactly once with
        the validation error fed back to the model.

        Never raises. Returns StructuredResponse with result=None on permanent
        failure so callers can record and continue.
        """
        resp = self.chat(messages)
        result, error = self._parse(resp.content, schema)

        if result is not None:
            return StructuredResponse(result=result, raw=resp.content, retried=False, failure_reason=None)

        # One self-correction attempt
        correction_messages = messages + [
            LLMMessage(role="assistant", content=resp.content),
            LLMMessage(
                role="user",
                content=(
                    f"Your response failed schema validation with this error:\n{error}\n\n"
                    "Return only the corrected JSON object, nothing else."
                ),
            ),
        ]
        retry_resp = self.chat(correction_messages)
        result, error = self._parse(retry_resp.content, schema)

        if result is not None:
            return StructuredResponse(result=result, raw=retry_resp.content, retried=True, failure_reason=None)

        logger.warning("extract_structured: permanent failure after retry. error=%s raw=%r", error, retry_resp.content[:200])
        return StructuredResponse(result=None, raw=retry_resp.content, retried=True, failure_reason=error)

    @staticmethod
    def _parse(content: str, schema: Type[T]) -> tuple[Optional[T], Optional[str]]:
        """
        Strip code fences and prose, extract the first JSON object, validate.
        Returns (parsed, None) on success or (None, error_string) on failure.
        """
        # Strip markdown code fences
        text = re.sub(r"```(?:json)?", "", content).strip()

        # Find the first {...} block, allowing nested braces
        start = text.find("{")
        if start == -1:
            return None, "No JSON object found in response"

        depth, end = 0, -1
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break

        if end == -1:
            return None, "Unterminated JSON object"

        raw_json = text[start:end + 1]

        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            return None, f"JSON decode error: {exc}"

        try:
            return schema.model_validate(data), None
        except ValidationError as exc:
            # Summarise errors concisely so the retry prompt isn't bloated
            errors = "; ".join(
                f"{' -> '.join(str(l) for l in e['loc'])}: {e['msg']}"
                for e in exc.errors()
            )
            return None, f"Schema validation failed: {errors}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(self, messages: List[LLMMessage]) -> LLMResponse:
        """
        Send messages and return a structured response.
        Retries on rate limits and server errors with exponential backoff.
        Raises LLMError immediately on client errors (4xx except 429).
        """
        payload = [{"role": m.role, "content": m.content} for m in messages]

        for attempt in range(_MAX_RETRIES + 1):
            try:
                return self._call_fn(
                    model=self.model,
                    messages=payload,
                    timeout=self.timeout,
                )
            except LLMRateLimitError:
                if attempt == _MAX_RETRIES:
                    raise
                delay = _BACKOFF_BASE ** attempt
                logger.warning("Rate limit hit, retrying in %ss (attempt %d)", delay, attempt + 1)
                time.sleep(delay)
            except LLMServerError:
                if attempt == _MAX_RETRIES:
                    raise
                delay = _BACKOFF_BASE ** attempt
                logger.warning("Server error, retrying in %ss (attempt %d)", delay, attempt + 1)
                time.sleep(delay)
            # LLMError (client errors) propagates immediately — no retry

    # ------------------------------------------------------------------
    # Real call — only place the SDK is used
    # ------------------------------------------------------------------

    def _real_call(self, model: str, messages: list, timeout: int) -> LLMResponse:
        # Import is local so the SDK never leaks into other modules
        import openai  # noqa: PLC0415

        # Use Ollama's OpenAI-compatible local endpoint if no API key is set
        api_key = getattr(settings, "OPENAI_API_KEY", "") or "ollama"
        base_url = getattr(settings, "LLM_BASE_URL", "http://localhost:11434/v1")

        client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )

        try:
            resp = client.chat.completions.create(model=model, messages=messages, max_tokens=512)
        except openai.RateLimitError as exc:
            raise LLMRateLimitError(str(exc)) from exc
        except openai.InternalServerError as exc:
            raise LLMServerError(str(exc)) from exc
        except openai.APIConnectionError as exc:
            raise LLMServerError(str(exc)) from exc
        except openai.BadRequestError as exc:
            # 400 — malformed request; retrying will not help
            raise LLMError(str(exc)) from exc
        except openai.AuthenticationError as exc:
            raise LLMError(str(exc)) from exc
        except openai.APIStatusError as exc:
            # Catch-all for remaining 4xx — treat as unretryable
            if 400 <= exc.status_code < 500:
                raise LLMError(str(exc)) from exc
            raise LLMServerError(str(exc)) from exc

        usage = resp.usage
        tokens_in = usage.prompt_tokens
        tokens_out = usage.completion_tokens
        rates = _COST_PER_1K.get(model, {"input": 0.0, "output": 0.0})
        cost = (tokens_in / 1000 * rates["input"]) + (tokens_out / 1000 * rates["output"])

        return LLMResponse(
            content=resp.choices[0].message.content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=round(cost, 6),
            model=model,
        )
