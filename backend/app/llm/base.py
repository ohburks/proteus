"""LLM provider abstraction (design doc §14).

Separate concern from Chroma's embedding function (§3.3) — this governs the
LLM used for Exemplar/Personalized grading calls themselves.
"""
from dataclasses import dataclass
from typing import Callable, Protocol

SUPPORTED_PROVIDERS = ("openai", "anthropic", "gemini", "groq", "mistral", "github", "ollama", "tamu")

EmitFn = Callable[[str], None]


@dataclass(frozen=True)
class ProviderConfig:
    provider: str  # one of SUPPORTED_PROVIDERS
    model: str
    api_key: str | None  # None only valid for provider == "ollama"
    base_url: str | None = None  # required for provider == "ollama"


class LLMClient(Protocol):
    def complete(self, system_prompt: str, user_prompt: str, emit: EmitFn | None = None) -> str:
        """Return the raw text completion (expected to be a JSON object per §6.6).

        `emit`, if given, is called with a one-line status string (e.g. rate-limit
        retries) — wired up for the dev live-grading terminal (TESTING ONLY).
        """
        ...
