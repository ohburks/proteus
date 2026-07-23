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

from app.llm.base import SUPPORTED_PROVIDERS, ProviderConfig

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"


class KeyResolutionError(ValueError):
    pass


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
            return ProviderConfig(
                provider="ollama",
                model=byok_model or os.environ.get("OLLAMA_DEFAULT_MODEL", "llama3.1"),
                api_key=None,
                base_url=byok_base_url or os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
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
