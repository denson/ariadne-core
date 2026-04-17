"""Vision API client — Gemini native generateContent with inlineData.

Sends images to Gemini's native vision endpoint and returns text
descriptions. Uses the `x-goog-api-key` header.

See SPEC.md → "Provider constraints" for the request/response contract
and an explanation of why the OpenAI-compatible shim is not supported
for Ariadne's bundled vision client.
"""

from __future__ import annotations

import base64
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_PROMPT = (
    "Describe this image in detail. Include any text, data, charts, "
    "diagrams, or visual elements. Be specific about numbers, labels, "
    "and relationships shown."
)


@dataclass
class VisionConfig:
    """Configuration for the vision API client."""

    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    prompt: str = DEFAULT_PROMPT


class VisionClient:
    """Client for describing images via an OpenAI-compatible vision API."""

    def __init__(self, config: VisionConfig) -> None:
        self._config = config
        model_path = config.model
        if not model_path.startswith("models/"):
            model_path = f"models/{model_path}"
        self._endpoint = (
            f"{config.base_url.rstrip('/')}/{model_path}:generateContent"
        )

    def describe_image_from_path(self, image_path: str) -> str:
        """Describe an image from a local file path.

        Args:
            image_path: Path to the image file.

        Returns:
            Text description of the image.

        Raises:
            FileNotFoundError: If the image file doesn't exist.
            RuntimeError: If the API call fails.
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        mime_type = mimetypes.guess_type(str(path))[0] or "image/png"
        data = base64.b64encode(path.read_bytes()).decode("utf-8")
        return self.describe_image_from_base64(data, mime_type=mime_type)

    def describe_image_from_url(self, image_url: str) -> str:
        """Describe an image from a URL.

        Fetches the URL bytes and sends them as inline data. Gemini's
        native generateContent does not accept arbitrary HTTP(S) image
        URLs; it requires inline base64 or a Gemini-managed file URI.

        Args:
            image_url: HTTP(S) URL to the image.

        Returns:
            Text description of the image.

        Raises:
            RuntimeError: If the URL fetch or the API call fails.
        """
        parsed = urlparse(image_url)
        if parsed.scheme not in ("http", "https"):
            raise RuntimeError(
                f"describe_image_from_url only accepts http(s) URLs, got: {image_url}"
            )
        try:
            with urlopen(image_url) as resp:
                img_bytes = resp.read()
                content_type = resp.headers.get("Content-Type", "")
        except Exception as e:
            raise RuntimeError(f"Failed to fetch image URL {image_url}: {e}") from e

        mime_type = content_type.split(";")[0].strip() if content_type else ""
        if not mime_type or not mime_type.startswith("image/"):
            guessed = mimetypes.guess_type(image_url)[0]
            mime_type = guessed or "image/png"

        data = base64.b64encode(img_bytes).decode("utf-8")
        return self.describe_image_from_base64(data, mime_type=mime_type)

    def describe_image_from_base64(
        self, data: str, mime_type: str = "image/png"
    ) -> str:
        """Describe an image from base64-encoded data.

        This is the terminal method — all other describe_image_* methods
        route through here.

        Args:
            data: Base64-encoded image data.
            mime_type: MIME type of the image.

        Returns:
            Text description of the image.

        Raises:
            RuntimeError: If the API call fails.
        """
        return self._call_vision_api(mime_type=mime_type, b64_data=data)

    def _call_vision_api(self, mime_type: str, b64_data: str) -> str:
        """Call Gemini's native generateContent with an inline image.

        Args:
            mime_type: MIME type of the image (e.g. "image/png").
            b64_data: Base64-encoded image bytes.

        Returns:
            Text description from the model.
        """
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": b64_data,
                            }
                        },
                        {"text": self._config.prompt},
                    ]
                }
            ],
            "generationConfig": {"maxOutputTokens": 1024},
        }

        body = json.dumps(payload).encode("utf-8")
        req = Request(
            self._endpoint,
            data=body,
            # NOTE FOR FUTURE AGENTS — native Gemini endpoint, not OpenAI-compat.
            # Ariadne's vision client calls Gemini's native
            # `:generateContent` with inlineData image parts and the
            # `x-goog-api-key` header. The OpenAI-compatible shim at
            # `/v1beta/openai/chat/completions` is NOT supported here —
            # Google's `AQ.*`-format keys reject every auth variant on
            # that path.
            #
            # If you swap to a different OpenAI-compatible provider
            # (OpenAI proper, Together, Groq, etc.), this whole module
            # needs a rewrite — endpoint construction, payload shape
            # (chat/completions with image_url parts), response parser,
            # and auth header all differ. Don't build a provider
            # abstraction here; let the configuring agent read the
            # provider's docs and pick a concrete path. See SPEC.md →
            # "Provider constraints" for the current native contract.
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self._config.api_key,
            },
            method="POST",
        )

        try:
            with urlopen(req) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            # Native response: candidates[0].content.parts[].text
            # Concatenate all text parts (usually one).
            candidates = result.get("candidates") or []
            if not candidates:
                raise RuntimeError(
                    f"Vision API returned no candidates: {result}"
                )
            parts = candidates[0].get("content", {}).get("parts") or []
            text_parts = [p.get("text", "") for p in parts if "text" in p]
            if not text_parts:
                raise RuntimeError(
                    f"Vision API returned no text parts: {result}"
                )
            return "".join(text_parts).strip()
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Vision API call failed: {e}") from e
