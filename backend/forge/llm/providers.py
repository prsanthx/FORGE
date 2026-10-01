"""Remote LLM connectors.

Every provider exposes the same complete()/health() shape. Token counts use the
provider's usage fields when present, otherwise a character estimate from the
actual prompt and completion.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from forge.llm.base import LLMError, LLMResponse, messages_text
from forge.llm.mock_agent import MockLLM
from forge.util import estimate_tokens

PROVIDER_NAMES = (
    "mock",
    "ollama",
    "lmstudio",
    "huggingface",
    "nvidia_nim",
    "google",
    "openai_compat",
    "anthropic",
)

DEFAULTS = {
    "ollama": {"base_url": "http://127.0.0.1:11434", "model": "llama3.2:3b", "api_key_env": ""},
    "lmstudio": {"base_url": "http://127.0.0.1:1234/v1", "model": "local-model", "api_key_env": ""},
    "huggingface": {
        "base_url": "https://router.huggingface.co/v1",
        "model": "Qwen/Qwen2.5-Coder-7B-Instruct",
        "api_key_env": "HF_TOKEN",
    },
    "nvidia_nim": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "meta/llama-3.1-8b-instruct",
        "api_key_env": "NVIDIA_API_KEY",
    },
    "google": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "model": "gemini-2.0-flash",
        "api_key_env": "GOOGLE_API_KEY",
    },
    "openai_compat": {
        "base_url": "http://127.0.0.1:8001/v1",
        "model": "gpt-4o-mini",
        "api_key_env": "OPENAI_API_KEY",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com",
        "model": "claude-3-5-haiku-latest",
        "api_key_env": "ANTHROPIC_API_KEY",
    },
    "mock": {"base_url": "", "model": "mock-small", "api_key_env": ""},
}


def cache_usage(usage: dict[str, Any] | None) -> tuple[int, int]:
    """Read prefix-cache counters from OpenAI, DeepSeek, Gemini, or Anthropic usage."""
    usage = usage or {}
    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    if not isinstance(details, dict):
        details = {}
    read = int(
        details.get("cached_tokens")
        or usage.get("cached_tokens")
        or usage.get("cache_read_input_tokens")
        or usage.get("cachedContentTokenCount")
        or 0
    )
    write = int(usage.get("cache_creation_input_tokens") or usage.get("cache_write_tokens") or 0)
    return read, write


def _key(explicit: str | None, env_name: str | None) -> str:
    if explicit:
        return explicit
    if env_name:
        return os.environ.get(env_name, "")
    return ""


class OpenAICompat:
    def __init__(self, name: str, base_url: str, model: str, api_key: str = "", *, prompt_cache: bool = True):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.prompt_cache = prompt_cache

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def complete(self, messages, *, temperature=0.2, max_tokens=2048, json_mode=False) -> LLMResponse:
        url = self.base_url + "/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(url, json=payload, headers=self._headers())
                if response.status_code >= 400 and json_mode:
                    payload.pop("response_format", None)
                    response = await client.post(url, json=payload, headers=self._headers())
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"{self.name} request failed: {exc}") from exc
        text = data["choices"][0]["message"].get("content") or ""
        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or estimate_tokens(messages_text(messages)))
        completion_tokens = int(usage.get("completion_tokens") or estimate_tokens(text))
        cache_read, cache_write = cache_usage(usage) if self.prompt_cache else (0, 0)
        return LLMResponse(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=(time.perf_counter() - started) * 1000,
            provider=self.name,
            model=self.model,
            estimated_tokens=not usage,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        )

    async def health(self) -> dict[str, Any]:
        url = self.base_url + "/models"
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(url, headers=self._headers())
            ok = response.status_code < 500
            return {"provider": self.name, "ok": ok, "detail": f"HTTP {response.status_code}"}
        except httpx.HTTPError as exc:
            return {"provider": self.name, "ok": False, "detail": str(exc)}


class OllamaProvider:
    def __init__(self, base_url: str, model: str, *, prompt_cache: bool = True):
        self.name = "ollama"
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.prompt_cache = prompt_cache

    async def complete(self, messages, *, temperature=0.2, max_tokens=2048, json_mode=False) -> LLMResponse:
        url = self.base_url + "/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            # Keep the model loaded so its KV cache survives the next step of this run.
            "keep_alive": -1 if self.prompt_cache else 0,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"ollama request failed: {exc}") from exc
        text = (data.get("message") or {}).get("content") or ""
        prompt_tokens = int(data.get("prompt_eval_count") or estimate_tokens(messages_text(messages)))
        completion_tokens = int(data.get("eval_count") or estimate_tokens(text))
        return LLMResponse(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=(time.perf_counter() - started) * 1000,
            provider=self.name,
            model=self.model,
            estimated_tokens="prompt_eval_count" not in data,
        )

    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=4) as client:
                response = await client.get(self.base_url + "/api/tags")
            return {"provider": self.name, "ok": response.status_code == 200, "detail": f"HTTP {response.status_code}"}
        except httpx.HTTPError as exc:
            return {"provider": self.name, "ok": False, "detail": str(exc)}


class GoogleProvider:
    def __init__(self, model: str, api_key: str, base_url: str, *, prompt_cache: bool = True):
        self.name = "google"
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.prompt_cache = prompt_cache

    async def complete(self, messages, *, temperature=0.2, max_tokens=2048, json_mode=False) -> LLMResponse:
        if not self.api_key:
            raise LLMError("Google API key is missing. Set GOOGLE_API_KEY or pass api_key.")
        system = ""
        contents = []
        for message in messages:
            if message.get("role") == "system":
                system += message.get("content") or ""
                continue
            role = "model" if message.get("role") == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": message.get("content") or ""}]})
        body: dict[str, Any] = {
            "contents": contents or [{"role": "user", "parts": [{"text": ""}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        url = f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(url, json=body)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"google request failed: {exc}") from exc
        parts = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [{}])
        text = "".join(part.get("text") or "" for part in parts)
        usage = data.get("usageMetadata") or {}
        cache_read, cache_write = cache_usage(usage) if self.prompt_cache else (0, 0)
        return LLMResponse(
            text=text,
            prompt_tokens=int(usage.get("promptTokenCount") or estimate_tokens(messages_text(messages))),
            completion_tokens=int(usage.get("candidatesTokenCount") or estimate_tokens(text)),
            latency_ms=(time.perf_counter() - started) * 1000,
            provider=self.name,
            model=self.model,
            estimated_tokens=not usage,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        )

    async def health(self) -> dict[str, Any]:
        if not self.api_key:
            return {"provider": self.name, "ok": False, "detail": "missing API key"}
        url = f"{self.base_url}/models?key={self.api_key}"
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get(url)
            return {"provider": self.name, "ok": response.status_code == 200, "detail": f"HTTP {response.status_code}"}
        except httpx.HTTPError as exc:
            return {"provider": self.name, "ok": False, "detail": str(exc)}


class HuggingFaceProvider(OpenAICompat):
    """Router uses the OpenAI-compatible API. The classic inference endpoint is separate."""

    def __init__(self, base_url: str, model: str, api_key: str):
        super().__init__("huggingface", base_url, model, api_key)
        self.classic = "api-inference.huggingface.co" in base_url

    async def complete(self, messages, *, temperature=0.2, max_tokens=2048, json_mode=False) -> LLMResponse:
        if not self.classic:
            return await super().complete(
                messages, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode
            )
        url = self.base_url.rstrip("/") + f"/models/{self.model}"
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    url,
                    json={"inputs": messages_text(messages)[-12000:], "parameters": {"max_new_tokens": max_tokens, "temperature": temperature}},
                    headers=self._headers(),
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"huggingface request failed: {exc}") from exc
        if isinstance(data, list) and data:
            text = data[0].get("generated_text") or ""
        elif isinstance(data, dict):
            text = data.get("generated_text") or data.get("error") or ""
        else:
            text = str(data)
        return LLMResponse(
            text=text,
            prompt_tokens=estimate_tokens(messages_text(messages)),
            completion_tokens=estimate_tokens(text),
            latency_ms=(time.perf_counter() - started) * 1000,
            provider=self.name,
            model=self.model,
            estimated_tokens=True,
        )


class AnthropicProvider:
    """Explicit cache breakpoint on the stable system prefix, plus usage counters."""

    def __init__(self, model: str, api_key: str, base_url: str, *, prompt_cache: bool = True):
        self.name = "anthropic"
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.prompt_cache = prompt_cache

    async def complete(self, messages, *, temperature=0.2, max_tokens=2048, json_mode=False) -> LLMResponse:
        if not self.api_key:
            raise LLMError("Anthropic API key is missing. Set ANTHROPIC_API_KEY or pass api_key.")
        system = []
        chat = []
        for message in messages:
            content = message.get("content") or ""
            if message.get("role") == "system":
                block: dict[str, Any] = {"type": "text", "text": content}
                if self.prompt_cache:
                    block["cache_control"] = {"type": "ephemeral"}
                system.append(block)
                continue
            chat.append({"role": "assistant" if message.get("role") == "assistant" else "user", "content": content})
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": chat or [{"role": "user", "content": ""}],
        }
        if system:
            body["system"] = system
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(self.base_url + "/v1/messages", json=body, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"anthropic request failed: {exc}") from exc
        text = "".join(part.get("text") or "" for part in data.get("content") or [] if isinstance(part, dict))
        usage = data.get("usage") or {}
        cache_read, cache_write = cache_usage(usage) if self.prompt_cache else (0, 0)
        return LLMResponse(
            text=text,
            prompt_tokens=int(usage.get("input_tokens") or estimate_tokens(messages_text(messages))),
            completion_tokens=int(usage.get("output_tokens") or estimate_tokens(text)),
            latency_ms=(time.perf_counter() - started) * 1000,
            provider=self.name,
            model=self.model,
            estimated_tokens=not usage,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        )

    async def health(self) -> dict[str, Any]:
        if not self.api_key:
            return {"provider": self.name, "ok": False, "detail": "missing API key"}
        return {"provider": self.name, "ok": True, "detail": "key is set"}


def build_provider(cfg: dict[str, Any], override: dict[str, Any] | None = None):
    from forge.core.context import resolve_policy

    override = override or {}
    llm_cfg = cfg.get("llm") or {}
    name = (override.get("provider") or llm_cfg.get("provider") or "mock").lower()
    defaults = DEFAULTS.get(name, DEFAULTS["openai_compat"])
    model = override.get("model") or llm_cfg.get("model") or defaults["model"]
    base_url = override.get("base_url") or llm_cfg.get("base_url") or defaults["base_url"]
    env_name = override.get("api_key_env") or llm_cfg.get("api_key_env") or defaults.get("api_key_env")
    api_key = _key(override.get("api_key"), env_name)
    prompt_cache = bool(resolve_policy(cfg).get("prompt_cache"))
    if name == "mock":
        return MockLLM(model=model)
    if name == "ollama":
        return OllamaProvider(base_url or defaults["base_url"], model, prompt_cache=prompt_cache)
    if name == "google":
        return GoogleProvider(model, api_key, base_url or defaults["base_url"], prompt_cache=prompt_cache)
    if name == "huggingface":
        return HuggingFaceProvider(base_url or defaults["base_url"], model, api_key)
    if name == "anthropic":
        return AnthropicProvider(model, api_key, base_url or defaults["base_url"], prompt_cache=prompt_cache)
    if name in {"lmstudio", "nvidia_nim", "openai_compat"}:
        return OpenAICompat(name, base_url or defaults["base_url"], model, api_key, prompt_cache=prompt_cache)
    raise LLMError(f"unknown provider '{name}'")
