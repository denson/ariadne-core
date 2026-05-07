"""Text encoding detection and LLM language validation for .txt files.

Uses charset-normalizer (transitive dependency of MarkItDown) for encoding
detection, and Gemini's native `:generateContent` endpoint for a text-only
LLM call that confirms the decoded text is coherent (not mojibake). Reuses
the image-enrichment config (`ImageEnrichmentConfig`) so operators don't
have to configure a second provider.

See SPEC.md → "Provider constraints" for the request/response contract
and an explanation of why the OpenAI-compatible shim is not supported
for Ariadne's bundled language validator.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

from charset_normalizer import from_bytes, from_path


def detect_and_decode(path: Path) -> tuple[str, str, float]:
    """Decode a text file with automatic encoding detection.

    Returns (decoded_text, detected_encoding, confidence).
    Confidence is 0.0-1.0 from charset-normalizer.
    """
    result = from_path(str(path)).best()
    if result is None:
        # Could not detect any encoding -- fall back to latin-1
        # (maps every byte to a character, never throws).
        # The LLM layer will catch if this produced garbage.
        raw = path.read_bytes().decode("latin-1")
        return raw, "latin-1-fallback", 0.0
    return str(result), result.encoding, result.coherence


def detect_and_decode_bytes(content: bytes, source_file: str) -> tuple[str, str, float]:
    """Decode raw bytes with automatic encoding detection.

    Sibling of ``detect_and_decode(Path)`` for the bytes-only ingest path
    (Batch G / ariadne--16a). Same charset-normalizer call shape; takes
    bytes directly instead of reading from disk so the canonical
    fingerprint→extraction flow does not re-touch the source. The
    ``source_file`` argument is unused by detection but kept in the
    signature so future loggers / error messages can quote the origin.
    """
    result = from_bytes(content).best()
    if result is None:
        # Symmetric latin-1 fallback (see detect_and_decode above).
        return content.decode("latin-1"), "latin-1-fallback", 0.0
    return str(result), result.encoding, result.coherence


@dataclass
class LanguageValidation:
    coherent: bool
    language: str       # ISO 639-1 code or "unknown"
    script: str         # "Latin", "Cyrillic", "Arabic", "CJK", etc. or "unknown"
    confidence: str     # "high", "medium", "low"
    notes: str          # explanation if low confidence or not coherent
    model: str          # which LLM model was used
    skipped: bool       # True if LLM validation was skipped (no API key)


_VALIDATION_PROMPT = """\
Analyze this text sample. Respond with ONLY a JSON object, no other text:
{{
  "coherent": true/false,
  "language": "ISO 639-1 code or 'unknown'",
  "script": "Latin/Cyrillic/Arabic/CJK/etc or 'unknown'",
  "confidence": "high/medium/low",
  "notes": "brief explanation if low confidence or not coherent"
}}

Text sample:
\"\"\"
{text_sample}
\"\"\""""


def validate_language(text: str, config) -> LanguageValidation:
    """Validate decoded text via LLM to confirm it's coherent.

    Uses the image enrichment config (ImageEnrichmentConfig) for the API call.
    If no API key is configured, skips validation gracefully.

    Args:
        text: Decoded text to validate.
        config: ImageEnrichmentConfig instance.

    Returns:
        LanguageValidation with coherence/language/script results.
    """
    if not config.api_key:
        return LanguageValidation(
            coherent=True,
            language="unknown",
            script="unknown",
            confidence="low",
            notes="LLM validation skipped -- no image enrichment API key configured",
            model=config.model,
            skipped=True,
        )

    first_500 = text[:500]
    prompt = _VALIDATION_PROMPT.format(text_sample=first_500)
    model_path = config.model
    if not model_path.startswith("models/"):
        model_path = f"models/{model_path}"
    endpoint = f"{config.base_url.rstrip('/')}/{model_path}:generateContent"

    # Native Gemini text-only payload.
    # See SPEC.md → "Provider constraints" → generateContent contract (text-only).
    payload = {
        "contents": [
            {"parts": [{"text": prompt}]}
        ],
        "generationConfig": {"maxOutputTokens": 256},
    }

    body = json.dumps(payload).encode("utf-8")
    req = Request(
        endpoint,
        data=body,
        # NOTE FOR FUTURE AGENTS — native Gemini endpoint, not OpenAI-compat.
        # Ariadne's language validator calls Gemini's native
        # `:generateContent` with a text-only part and the
        # `x-goog-api-key` header. The OpenAI-compatible shim at
        # `/v1beta/openai/chat/completions` is NOT supported here —
        # Google's `AQ.*`-format keys reject every auth variant on
        # that path.
        #
        # If you swap to a different OpenAI-compatible provider
        # (OpenAI proper, Together, Groq, etc.), this whole function
        # needs a rewrite — endpoint construction, payload shape
        # (chat/completions with messages), response parser, and
        # auth header all differ. Don't build a provider abstraction
        # here; let the configuring agent read the provider's docs
        # and pick a concrete path. See SPEC.md → "Provider
        # constraints" for the current native contract.
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": config.api_key,
        },
        method="POST",
    )

    try:
        with urlopen(req) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        # Native response: candidates[0].content.parts[].text
        candidates = result.get("candidates") or []
        if not candidates:
            raise RuntimeError(
                f"generateContent returned no candidates: {result}"
            )
        parts = candidates[0].get("content", {}).get("parts") or []
        text_parts = [p.get("text", "") for p in parts if "text" in p]
        if not text_parts:
            raise RuntimeError(
                f"generateContent returned no text parts: {result}"
            )
        content = "".join(text_parts).strip()
    except Exception as e:
        return LanguageValidation(
            coherent=True,
            language="unknown",
            script="unknown",
            confidence="low",
            notes=f"LLM API call failed: {e}",
            model=config.model,
            skipped=False,
        )

    # Gemini occasionally wraps JSON replies in a ```json ... ``` fence
    # when responseMimeType is not explicitly set. Strip it before parsing.
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        # Drop the opening fence (may be ```json or ```)
        lines = lines[1:]
        # Drop the closing fence if present
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        return LanguageValidation(
            coherent=True,
            language="unknown",
            script="unknown",
            confidence="low",
            notes="LLM response was not valid JSON",
            model=config.model,
            skipped=False,
        )

    return LanguageValidation(
        coherent=parsed.get("coherent", True),
        language=parsed.get("language", "unknown"),
        script=parsed.get("script", "unknown"),
        confidence=parsed.get("confidence", "low"),
        notes=parsed.get("notes", ""),
        model=config.model,
        skipped=False,
    )
