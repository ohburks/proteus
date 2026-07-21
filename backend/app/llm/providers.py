"""Provider clients (design doc §14.1: OpenAI, Claude, Gemini, Groq, Mistral,
GitHub Models, Ollama — server-key or BYO-key).

stdlib `urllib` by default (§1) — no SDK dependency for the common REST
call shape. `openai`/`anthropic` SDKs are optional/available but not
required for these calls.
"""
import json
import time
import urllib.error
import urllib.request

from app.llm.base import EmitFn, LLMClient, ProviderConfig

_TIMEOUT_S = 120
_MAX_RETRIES = 5
_RETRY_BACKOFF_S = 5


def _post_json(url: str, headers: dict[str, str], body: dict, emit: EmitFn | None = None) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers}, method="POST")
    for attempt in range(_MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", "replace")
            if e.code == 429 and attempt < _MAX_RETRIES:
                retry_after = e.headers.get("Retry-After") if e.headers else None
                wait_s = float(retry_after) if retry_after else _RETRY_BACKOFF_S * (attempt + 1)
                if emit:
                    emit(f"Rate limited (429) calling {url} — retrying in {wait_s:.0f}s (attempt {attempt + 1}/{_MAX_RETRIES})")
                time.sleep(wait_s)
                continue
            raise RuntimeError(f"LLM request to {url} failed: {e.code} {body_text}") from e


class _OpenAICompatibleClient:
    """Shared shape for OpenAI, Groq, Mistral, GitHub Models, Ollama (/v1 endpoint)."""

    def __init__(self, base_url: str, model: str, api_key: str | None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key

    def complete(self, system_prompt: str, user_prompt: str, emit: EmitFn | None = None) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        result = _post_json(f"{self.base_url}/chat/completions", headers, body, emit=emit)
        return result["choices"][0]["message"]["content"]


class _AnthropicClient:
    def __init__(self, model: str, api_key: str):
        self.model = model
        self.api_key = api_key

    def complete(self, system_prompt: str, user_prompt: str, emit: EmitFn | None = None) -> str:
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        body = {
            "model": self.model,
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        result = _post_json("https://api.anthropic.com/v1/messages", headers, body, emit=emit)
        return "".join(block["text"] for block in result["content"] if block["type"] == "text")


class _GeminiClient:
    def __init__(self, model: str, api_key: str):
        self.model = model
        self.api_key = api_key

    def complete(self, system_prompt: str, user_prompt: str, emit: EmitFn | None = None) -> str:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        body = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
        }
        result = _post_json(url, {}, body, emit=emit)
        return result["candidates"][0]["content"]["parts"][0]["text"]


def build_client(config: ProviderConfig) -> LLMClient:
    if config.provider == "openai":
        return _OpenAICompatibleClient("https://api.openai.com/v1", config.model, config.api_key)
    if config.provider == "groq":
        return _OpenAICompatibleClient("https://api.groq.com/openai/v1", config.model, config.api_key)
    if config.provider == "mistral":
        return _OpenAICompatibleClient("https://api.mistral.ai/v1", config.model, config.api_key)
    if config.provider == "github":
        return _OpenAICompatibleClient("https://models.inference.ai.azure.com", config.model, config.api_key)
    if config.provider == "ollama":
        return _OpenAICompatibleClient(f"{config.base_url}/v1", config.model, None)
    if config.provider == "anthropic":
        return _AnthropicClient(config.model, config.api_key)
    if config.provider == "gemini":
        return _GeminiClient(config.model, config.api_key)
    raise ValueError(f"Unsupported provider: {config.provider!r}")
