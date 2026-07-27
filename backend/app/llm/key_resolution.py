"""Key resolution modes, in resolution order (design doc §14.2).

1. Request-level BYOK — caller supplies provider + key per request, overrides
   everything else.
2. Server .env key — a default provider/key configured at deployment level.
3. Local Ollama — no key required; provider="ollama" with a base URL,
   selected explicitly, not a silent fallback-if-others-fail path.

§14.3: both grading paths in a single run share one ProviderConfig — provider
is a run-level setting, not a per-path setting.
"""
import os
from urllib.parse import urlsplit

from app.llm.base import SUPPORTED_PROVIDERS, ProviderConfig

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"


class KeyResolutionError(ValueError):
    pass


def _normalize_origin(base_url: str) -> str | None:
    """Reduce a URL to a bare scheme://host:port origin, or None if it isn't a
    plain http(s) URL. Path/query/fragment and any embedded userinfo are
    dropped — the SSRF fix below compares and rebuilds from this, so a value
    like ``http://ollama-host:11434/../admin`` can't smuggle a path past an
    origin allowlist check."""
    parts = urlsplit(base_url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    if parts.username or parts.password:
        return None
    try:
        port = parts.port
    except ValueError:
        return None  # non-numeric port
    if port is None:
        port = 443 if parts.scheme == "https" else 80
    return f"{parts.scheme}://{parts.hostname.lower()}:{port}"


def _allowed_ollama_origins() -> set[str]:
    """Origins a *request-supplied* Ollama base_url is allowed to target.

    Ollama's whole point is a local endpoint, so we can't just blocklist
    loopback/private ranges — instead the deployment declares which endpoints
    it trusts. The server's own configured endpoint (OLLAMA_BASE_URL, or the
    built-in localhost default) is always allowed; operators add more via
    OLLAMA_ALLOWED_BASE_URLS (comma-separated). Anything else is rejected, so
    an authenticated caller can't point the server at arbitrary internal hosts
    (cloud metadata, internal admin panels, port scans) — see §14.2 BYOK."""
    origins = {_normalize_origin(os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL))}
    for raw in os.environ.get("OLLAMA_ALLOWED_BASE_URLS", "").split(","):
        if raw.strip():
            origins.add(_normalize_origin(raw))
    return {o for o in origins if o}


def _resolve_request_ollama_base_url(byok_base_url: str) -> str:
    """Validate a caller-supplied Ollama base_url against the allowlist and
    return the normalized origin actually used for outbound requests."""
    origin = _normalize_origin(byok_base_url)
    if origin is None:
        raise KeyResolutionError(
            "Invalid Ollama base_url: expected an http(s) URL with no embedded credentials"
        )
    if origin not in _allowed_ollama_origins():
        raise KeyResolutionError(
            f"Ollama base_url {origin!r} is not permitted. Add it to OLLAMA_ALLOWED_BASE_URLS "
            "on the server to allow it."
        )
    return origin


def resolve_provider_config(
    byok_provider: str | None = None,
    byok_key: str | None = None,
    byok_model: str | None = None,
    byok_base_url: str | None = None,
) -> ProviderConfig:
    # 1. Request-level BYOK
    if byok_provider:
        if byok_provider not in SUPPORTED_PROVIDERS:
            # Guard before _default_model[provider], which would otherwise raise
            # a bare KeyError and surface as a 500. Callers catch
            # KeyResolutionError and return a clean 400.
            raise KeyResolutionError(
                f"Unsupported provider {byok_provider!r}. Supported: {', '.join(SUPPORTED_PROVIDERS)}"
            )
        if byok_provider == "ollama":
            # A request-supplied base_url is the SSRF surface, so it's validated
            # against the operator allowlist; falling back to the server's own
            # OLLAMA_BASE_URL (trusted config) needs no check.
            base_url = (
                _resolve_request_ollama_base_url(byok_base_url)
                if byok_base_url
                else os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)
            )
            return ProviderConfig(
                provider="ollama",
                model=byok_model or os.environ.get("OLLAMA_DEFAULT_MODEL", "llama3.1"),
                api_key=None,
                base_url=base_url,
            )
        if not byok_key:
            raise KeyResolutionError(f"BYOK request for provider={byok_provider!r} is missing an API key")
        return ProviderConfig(provider=byok_provider, model=byok_model or _default_model(byok_provider), api_key=byok_key)

    # 2. Server .env key
    env_provider = os.environ.get("LLM_PROVIDER")
    if env_provider:
        if env_provider == "ollama":
            return ProviderConfig(
                provider="ollama",
                model=os.environ.get("OLLAMA_DEFAULT_MODEL", "llama3.1"),
                api_key=None,
                base_url=os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
            )
        env_key = os.environ.get(f"{env_provider.upper()}_API_KEY")
        if not env_key:
            raise KeyResolutionError(f"LLM_PROVIDER={env_provider!r} set but {env_provider.upper()}_API_KEY is missing")
        return ProviderConfig(
            provider=env_provider,
            model=os.environ.get("LLM_MODEL", _default_model(env_provider)),
            api_key=env_key,
        )

    # 3. Local Ollama, explicit opt-in only if nothing else configured
    if os.environ.get("OLLAMA_BASE_URL") or os.environ.get("LLM_PROVIDER_FALLBACK") == "ollama":
        return ProviderConfig(
            provider="ollama",
            model=os.environ.get("OLLAMA_DEFAULT_MODEL", "llama3.1"),
            api_key=None,
            base_url=os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
        )

    raise KeyResolutionError(
        "No LLM provider configured: supply request-level BYOK, set LLM_PROVIDER/"
        "<PROVIDER>_API_KEY in the server .env, or set OLLAMA_BASE_URL for local Ollama."
    )


def _default_model(provider: str) -> str:
    return {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-sonnet-5",
        "gemini": "gemini-2.5-flash",
        "groq": "llama-3.3-70b-versatile",
        "mistral": "mistral-large-latest",
        "github": "gpt-4o-mini",
        "tamu": "protected.gpt-4o",
    }[provider]
