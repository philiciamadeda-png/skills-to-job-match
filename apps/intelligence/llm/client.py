"""
LLM client wrapper.

The OpenAI SDK is imported only here. Nothing else in the codebase touches it.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from django.conf import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cost table — update when model pricing changes
# ---------------------------------------------------------------------------
_COST_PER_1K = {
    "gpt-4o-mini": {"input": 0.000150, "output": 0.000600},
    "gpt-4o":      {"input": 0.002500, "output": 0.010000},
}

_DEFAULT_MODEL = "gpt-4o-mini"
_DEFAULT_TIMEOUT = 30          # seconds
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

        client = openai.OpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=timeout,
        )

        try:
            resp = client.chat.completions.create(model=model, messages=messages)
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
