"""LLM adapter.

One interface, two implementations:

* ``OpenAICompatibleClient`` — any ``/chat/completions`` endpoint (OpenAI,
  OpenRouter, Together, a local vLLM server) configured purely by environment
  variables.
* ``NullLLMClient`` — always returns "unavailable". This is what runs when no
  key is configured, and it is a *supported* mode: every feature degrades to
  deterministic output rather than breaking.

Token usage is tracked so the UI can show what a research session cost.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..config import LLMSettings, get_llm_settings


@dataclass
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, usage: dict | None) -> None:
        if not usage:
            self.calls += 1
            return
        self.prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
        self.completion_tokens += int(usage.get("completion_tokens", 0) or 0)
        self.calls += 1


@dataclass
class LLMResponse:
    """Always returned — ``ok`` says whether there is anything usable inside."""

    ok: bool
    text: str = ""
    data: dict | list | None = None
    error: str = ""
    usage: dict = field(default_factory=dict)
    model: str = ""

    @property
    def unavailable(self) -> bool:
        return not self.ok


class LLMClient(ABC):
    """The contract the rest of the application codes against."""

    name: str = "abstract"

    @abstractmethod
    def complete(self, system: str, user: str, *, json_mode: bool = False,
                 max_tokens: int | None = None, temperature: float | None = None) -> LLMResponse:
        ...

    @property
    def available(self) -> bool:
        return False

    def describe(self) -> str:
        return self.name


class NullLLMClient(LLMClient):
    """The fallback. Never errors, never fabricates, never calls anything."""

    name = "none (deterministic mode)"

    def __init__(self, reason: str = "No LLM configured.") -> None:
        self.reason = reason
        self.usage = LLMUsage()

    def complete(self, system: str, user: str, *, json_mode: bool = False,
                 max_tokens: int | None = None, temperature: float | None = None) -> LLMResponse:
        return LLMResponse(ok=False, error=self.reason)

    def describe(self) -> str:
        return f"Deterministic mode — {self.reason}"


class OpenAICompatibleClient(LLMClient):
    """Talks to any OpenAI-compatible chat-completions endpoint."""

    name = "openai-compatible"

    def __init__(self, settings: LLMSettings | None = None) -> None:
        self.settings = settings or get_llm_settings()
        self.usage = LLMUsage()

    @property
    def available(self) -> bool:
        return self.settings.is_usable

    def describe(self) -> str:
        return self.settings.describe()

    def complete(self, system: str, user: str, *, json_mode: bool = False,
                 max_tokens: int | None = None, temperature: float | None = None) -> LLMResponse:
        if not self.available:
            return LLMResponse(ok=False, error=self.settings.describe())

        import httpx

        payload: dict = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.settings.temperature if temperature is None else temperature,
            "max_tokens": max_tokens or self.settings.max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            response = httpx.post(
                f"{self.settings.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.settings.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.settings.timeout,
            )
        except Exception as exc:  # noqa: BLE001 — network problems must not crash the app
            return LLMResponse(ok=False, error=f"Could not reach the LLM endpoint: {exc}")

        if response.status_code == 401:
            return LLMResponse(ok=False, error="LLM rejected the API key (401). Check LLM_API_KEY.")
        if response.status_code == 429:
            return LLMResponse(ok=False, error="LLM rate limit reached (429). Try again shortly.")
        if response.status_code >= 400:
            return LLMResponse(
                ok=False,
                error=f"LLM error {response.status_code}: {response.text[:300]}",
            )

        try:
            body = response.json()
            text = body["choices"][0]["message"]["content"] or ""
        except Exception as exc:  # noqa: BLE001
            return LLMResponse(ok=False, error=f"Unexpected LLM response shape: {exc}")

        usage = body.get("usage") or {}
        self.usage.add(usage)

        result = LLMResponse(ok=True, text=text.strip(), usage=usage,
                             model=body.get("model", self.settings.model))
        if json_mode:
            parsed = parse_json(text)
            if parsed is None:
                return LLMResponse(
                    ok=False,
                    error="The model did not return valid JSON.",
                    text=text[:500],
                    usage=usage,
                )
            result.data = parsed
        return result


def parse_json(text: str) -> dict | list | None:
    """Tolerant JSON extraction — strips code fences and finds the outer object."""
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    match = re.search(r"[\{\[].*[\}\]]", cleaned, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def get_llm_client(settings: LLMSettings | None = None) -> LLMClient:
    """Factory. Returns a working client, or the Null client with a clear reason."""
    resolved = settings or get_llm_settings()
    if not resolved.enabled:
        return NullLLMClient("LLM_ENABLED is false — running in deterministic mode.")
    if not resolved.api_key:
        return NullLLMClient("LLM_ENABLED is true but LLM_API_KEY is empty.")
    return OpenAICompatibleClient(resolved)


#: Rough per-1M-token prices for common models, used only for a UI cost estimate.
#: Unknown models simply show no estimate rather than a made-up number.
APPROX_PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-sonnet-4": (3.00, 15.00),
    "llama-3.1-70b-instruct": (0.35, 0.40),
}


def estimate_cost_usd(model: str, usage: LLMUsage) -> float | None:
    key = next((k for k in APPROX_PRICES_USD_PER_MTOK if k in (model or "").lower()), None)
    if key is None:
        return None
    prompt_price, completion_price = APPROX_PRICES_USD_PER_MTOK[key]
    return round(
        usage.prompt_tokens / 1_000_000 * prompt_price
        + usage.completion_tokens / 1_000_000 * completion_price,
        6,
    )
