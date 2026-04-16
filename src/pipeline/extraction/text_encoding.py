"""Text encoding detection and LLM language validation for .txt files.

Uses charset-normalizer (transitive dependency of MarkItDown) for encoding
detection, and the existing image enrichment API config for an LLM validation
call that confirms the decoded text is coherent (not mojibake).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

from charset_normalizer import from_path


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
    endpoint = f"{config.base_url.rstrip('/')}/chat/completions"

    payload = {
        "model": config.model,
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 256,
    }

    body = json.dumps(payload).encode("utf-8")
    req = Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
        },
        method="POST",
    )

    try:
        with urlopen(req) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        content = result["choices"][0]["message"]["content"]
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

    try:
        parsed = json.loads(content)
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
