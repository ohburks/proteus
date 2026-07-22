"""Provider clients (design doc §14.1: OpenAI, Claude, Gemini, Groq, Mistral,
GitHub Models, Ollama — server-key or BYO-key).

stdlib `urllib` by default (§1) — no SDK dependency for the common REST
call shape. `openai`/`anthropic` SDKs are optional/available but not
required for these calls.
"""
import json
import threading
import time
import urllib.error
import urllib.request

from app.llm.base import EmitFn, LLMClient, ProviderConfig

_TIMEOUT_S = 120
_MAX_RETRIES = 5
_RETRY_BACKOFF_S = 5

# A server-supplied Retry-After beyond this isn't worth blocking the
# background grading thread for — fail fast instead. Free tiers (e.g. GitHub
# Models) can return a Retry-After reflecting a daily/longer-window quota,
# distinct from the per-minute cap already paced for below, and blindly
# sleeping for that would hang an entire assessment for hours with no way
# to cancel it.
_MAX_RETRY_AFTER_S = 60

# GitHub Models' free tier caps at 15 requests/min per model — a quota, not a
# model-capability limit. Pace calls to stay under it proactively so 429s
# become rare instead of routine; the reactive retry below stays as a
# fallback (e.g. a concurrent process sharing the same account's quota).
_GITHUB_MIN_INTERVAL_S = 4.2
_github_throttle_lock = threading.Lock()
_github_last_call_ts = 0.0


def _throttle_github(emit: EmitFn | None = None) -> None:
    global _github_last_call_ts
    with _github_throttle_lock:
        now = time.monotonic()
        earliest = _github_last_call_ts + _GITHUB_MIN_INTERVAL_S
        wait = max(0.0, earliest - now)
        _github_last_call_ts = now + wait
    if wait > 0.05:
        if emit:
            emit(f"Pacing GitHub Models request — waiting {wait:.1f}s to stay under the 15/min free-tier limit")
        time.sleep(wait)


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
                retry_after_header = e.headers.get("Retry-After") if e.headers else None
                retry_after = None
                if retry_after_header:
                    try:
                        retry_after = float(retry_after_header)
                    except ValueError:
                        retry_after = None  # e.g. an HTTP-date header — fall back to backoff
                if retry_after is not None and retry_after > _MAX_RETRY_AFTER_S:
                    raise RuntimeError(
                        f"LLM request to {url} was rate limited with a Retry-After of "
                        f"{retry_after:.0f}s, past the {_MAX_RETRY_AFTER_S}s cap — not retrying"
                    ) from e
                wait_s = retry_after if retry_after is not None else _RETRY_BACKOFF_S * (attempt + 1)
                if emit:
                    emit(f"Rate limited (429) calling {url} — retrying in {wait_s:.0f}s (attempt {attempt + 1}/{_MAX_RETRIES})")
                time.sleep(wait_s)
                continue
            raise RuntimeError(f"LLM request to {url} failed: {e.code} {body_text}") from e


class _OpenAICompatibleClient:
    """Shared shape for OpenAI, Groq, Mistral, GitHub Models, Ollama (/v1 endpoint)."""

    def __init__(self, base_url: str, model: str, api_key: str | None, throttle_github: bool = False):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self._throttle_github = throttle_github

    def complete(self, system_prompt: str, user_prompt: str, emit: EmitFn | None = None) -> str:
        if self._throttle_github:
            _throttle_github(emit)
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
        # Key goes in the x-goog-api-key header, never the URL: the URL is
        # embedded in retry/failure messages that reach the live grading
        # terminal and assessment error text, so a query-string key would
        # leak to the browser.
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )
        body = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
        }
        result = _post_json(url, {"x-goog-api-key": self.api_key}, body, emit=emit)
        return result["candidates"][0]["content"]["parts"][0]["text"]


def build_client(config: ProviderConfig) -> LLMClient:
    if config.provider == "openai":
        return _OpenAICompatibleClient("https://api.openai.com/v1", config.model, config.api_key)
    if config.provider == "groq":
        return _OpenAICompatibleClient("https://api.groq.com/openai/v1", config.model, config.api_key)
    if config.provider == "mistral":
        return _OpenAICompatibleClient("https://api.mistral.ai/v1", config.model, config.api_key)
    if config.provider == "github":
        return _OpenAICompatibleClient(
            "https://models.inference.ai.azure.com", config.model, config.api_key, throttle_github=True
        )
    if config.provider == "ollama":
        return _OpenAICompatibleClient(f"{config.base_url}/v1", config.model, None)
    if config.provider == "anthropic":
        return _AnthropicClient(config.model, config.api_key)
    if config.provider == "gemini":
        return _GeminiClient(config.model, config.api_key)
    raise ValueError(f"Unsupported provider: {config.provider!r}")
