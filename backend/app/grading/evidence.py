"""Verbatim-quote evidence verification (design doc §3.5).

Two distinct checks share this same normalization/match mechanic but run at
different times against different source texts — they are NOT the same call:

- Ingestion-time check (`verify_quote`, called from app.repositories.excerpts):
  verifies a *stored* excerpt's quote against whichever essay it claims to
  come from. Runs once, when the excerpt enters a corpus.
- Grading-time check (`verify_quote`, called from app.grading.engine):
  verifies a *newly produced* score's cited quotes against the essay
  currently being graded. Runs every grading call.

Retrieved precedent is never re-checked against the essay currently being
graded — a retrieved excerpt is a verified claim about a different, already-
graded essay, checked once at ingestion.

No tolerance for paraphrase: only whitespace/quote-char/case normalization.
"""
import re
import unicodedata

_QUOTE_CHARS = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "′": "'", "`": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "″": '"',
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    for src, dst in _QUOTE_CHARS.items():
        text = text.replace(src, dst)
    text = text.lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def verify_quote(quote: str, source_text: str) -> bool:
    """True iff `quote` appears verbatim (post-normalization) in `source_text`."""
    if not quote or not quote.strip():
        return False
    return normalize(quote) in normalize(source_text)


class EvidenceVerificationError(ValueError):
    """Raised when a quote fails verbatim-match verification."""

    def __init__(self, quote: str, context: str):
        self.quote = quote
        self.context = context
        super().__init__(f"Quote failed verbatim verification ({context}): {quote!r}")
