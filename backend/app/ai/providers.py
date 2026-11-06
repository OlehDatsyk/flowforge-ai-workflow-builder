"""Backend-only AI provider abstraction.

Add a provider by subclassing ``AIProvider``, registering it in ``PROVIDER_CLASSES``
and adding an entry to the integrations catalogue.
"""
from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

import anthropic
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Credential, Integration
from ..security import decrypt_json


class AIError(Exception):
    """A provider failed. The message never contains the API key."""

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class AIResponse:
    text: str
    data: Any
    provider: str
    model: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: Optional[float] = None


class AIProvider(ABC):
    name = "base"
    is_demo = False

    def __init__(self, api_key: str, model: str, timeout: float):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @abstractmethod
    def _call(self, system: str, prompt: str, schema: dict | None, max_tokens: int, effort: str) -> tuple[str, int | None, int | None]:
        """Returns (text, input_tokens, output_tokens)."""

    def complete(self, system: str, prompt: str, schema: dict | None = None, max_tokens: int = 4096, effort: str = "low") -> AIResponse:
        started = time.perf_counter()
        text, usage_in, usage_out = self._call(system, prompt, schema, max_tokens, effort)
        data = None
        if schema is not None:
            try:
                data = json.loads(_strip_fence(text))
            except json.JSONDecodeError as exc:
                raise AIError(f"{self.name} returned invalid JSON", retryable=True) from exc
        return AIResponse(text, data, self.name, self.model, usage_in, usage_out, (time.perf_counter() - started) * 1000)


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    return text


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def _client(self) -> anthropic.Anthropic:
        return anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout, max_retries=1)

    def _call(self, system, prompt, schema, max_tokens, effort):
        output_config: dict[str, Any] = {"effort": effort}
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        try:
            # Server-side fallback keeps a request alive if a safety classifier
            # false-positives on the primary model.
            response = self._client().beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config=output_config,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as exc:
            raise AIError("Anthropic rejected the API key") from exc
        except anthropic.PermissionDeniedError as exc:
            raise AIError("This Anthropic API key cannot use the configured model") from exc
        except anthropic.NotFoundError as exc:
            raise AIError(f"Anthropic model '{self.model}' was not found") from exc
        except anthropic.RateLimitError as exc:
            raise AIError("Anthropic rate limit reached", retryable=True) from exc
        except anthropic.APITimeoutError as exc:
            raise AIError(f"Anthropic request timed out after {self.timeout:.0f}s", retryable=True) from exc
        except anthropic.APIConnectionError as exc:
            raise AIError("Could not reach Anthropic", retryable=True) from exc
        except anthropic.APIStatusError as exc:
            raise AIError(f"Anthropic returned HTTP {exc.status_code}", retryable=exc.status_code >= 500) from exc
        if response.stop_reason == "refusal":
            raise AIError("Anthropic declined this request")
        if response.stop_reason == "max_tokens":
            raise AIError("Anthropic response was cut off at the token limit", retryable=False)
        text = "".join(block.text for block in response.content if block.type == "text")
        return text, response.usage.input_tokens, response.usage.output_tokens


class _HTTPProvider(AIProvider):
    transport: httpx.BaseTransport | None = None  # injected by tests

    def _post(self, url: str, headers: dict, payload: dict) -> dict:
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                response = client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise AIError(f"{self.name} request timed out after {self.timeout:.0f}s", retryable=True) from exc
        except httpx.TransportError as exc:
            raise AIError(f"Could not reach {self.name}", retryable=True) from exc
        if response.status_code in (401, 403):
            raise AIError(f"{self.name} rejected the API key")
        if response.status_code == 429:
            raise AIError(f"{self.name} rate limit reached", retryable=True)
        if response.status_code >= 400:
            raise AIError(f"{self.name} returned HTTP {response.status_code}", retryable=response.status_code >= 500)
        return response.json()


class OpenAIProvider(_HTTPProvider):
    name = "openai"

    def _call(self, system, prompt, schema, max_tokens, effort):
        payload: dict[str, Any] = {
            "model": self.model,
            "max_completion_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }
        if schema is not None:
            payload["response_format"] = {"type": "json_schema", "json_schema": {"name": "result", "strict": True, "schema": schema}}
        data = self._post("https://api.openai.com/v1/chat/completions", {"Authorization": f"Bearer {self.api_key}"}, payload)
        choice = data["choices"][0]
        if choice.get("message", {}).get("refusal"):
            raise AIError("OpenAI declined this request")
        usage = data.get("usage") or {}
        return choice["message"].get("content") or "", usage.get("prompt_tokens"), usage.get("completion_tokens")


class GeminiProvider(_HTTPProvider):
    name = "gemini"

    def _call(self, system, prompt, schema, max_tokens, effort):
        config: dict[str, Any] = {"maxOutputTokens": max_tokens}
        text = prompt
        if schema is not None:
            config["responseMimeType"] = "application/json"
            text = f"{prompt}\n\nRespond with JSON matching this schema:\n{json.dumps(schema)}"
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": config,
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        data = self._post(url, {"x-goog-api-key": self.api_key}, payload)
        candidates = data.get("candidates") or []
        if not candidates or not candidates[0].get("content"):
            raise AIError("Gemini returned no content (the request may have been blocked)")
        usage = data.get("usageMetadata") or {}
        out = "".join(p.get("text", "") for p in candidates[0]["content"].get("parts", []))
        return out, usage.get("promptTokenCount"), usage.get("candidatesTokenCount")


class DemoProvider:
    """Marker for demonstration mode: no provider call happens, ever."""

    name = "demo"
    model = "rule-based-demo"
    is_demo = True


PROVIDER_CLASSES: dict[str, type[AIProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
}


def _model_for(provider: str, override: str | None = None) -> str:
    settings = get_settings()
    return override or {
        "anthropic": settings.anthropic_model,
        "openai": settings.openai_model,
        "gemini": settings.gemini_model,
    }[provider]


def _env_key(provider: str) -> str:
    settings = get_settings()
    return {"anthropic": settings.anthropic_api_key, "openai": settings.openai_api_key, "gemini": settings.gemini_api_key}[provider]


def provider_from_credential(cred: Credential) -> AIProvider:
    if cred.type not in PROVIDER_CLASSES:
        raise AIError(f"Credential '{cred.name}' is not an AI provider key")
    data = decrypt_json(cred.encrypted_data)
    return PROVIDER_CLASSES[cred.type](data["api_key"], _model_for(cred.type, data.get("model")), get_settings().ai_timeout_seconds)


def resolve_provider(db: Session, workspace_id: str, credential_id: str | None = None) -> AIProvider | DemoProvider:
    """Explicit credential -> workspace integration -> server environment -> demo."""
    settings = get_settings()
    if credential_id:
        cred = db.scalar(select(Credential).where(Credential.id == credential_id, Credential.workspace_id == workspace_id))
        if cred is None:
            raise AIError("The selected AI credential does not exist in this workspace")
        return provider_from_credential(cred)
    rows = db.scalars(
        select(Integration).where(
            Integration.workspace_id == workspace_id,
            Integration.provider.in_(PROVIDER_CLASSES.keys()),
            Integration.enabled.is_(True),
            Integration.credential_id.is_not(None),
        )
    ).all()
    for row in rows:
        cred = db.get(Credential, row.credential_id)
        if cred is not None and cred.workspace_id == workspace_id:
            return provider_from_credential(cred)
    order = [settings.ai_default_provider] if settings.ai_default_provider in PROVIDER_CLASSES else []
    order += [p for p in PROVIDER_CLASSES if p not in order]
    for provider in order:
        key = _env_key(provider)
        if key:
            return PROVIDER_CLASSES[provider](key, _model_for(provider), settings.ai_timeout_seconds)
    return DemoProvider()
