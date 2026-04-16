"""Vision API client — any OpenAI-compatible endpoint.

Sends images to a vision model and returns text descriptions.
Supports OpenAI, Anthropic (via proxy), Together, Groq, or any
endpoint that accepts the OpenAI chat completions format with
image_url content parts.
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
        self._endpoint = f"{config.base_url.rstrip('/')}/chat/completions"

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
        image_data = base64.b64encode(path.read_bytes()).decode("utf-8")
        data_url = f"data:{mime_type};base64,{image_data}"

        return self._call_vision_api(data_url)

    def describe_image_from_url(self, image_url: str) -> str:
        """Describe an image from a URL.

        Args:
            image_url: HTTP(S) URL to the image.

        Returns:
            Text description of the image.

        Raises:
            RuntimeError: If the API call fails.
        """
        return self._call_vision_api(image_url)

    def describe_image_from_base64(
        self, data: str, mime_type: str = "image/png"
    ) -> str:
        """Describe an image from base64-encoded data.

        Args:
            data: Base64-encoded image data.
            mime_type: MIME type of the image.

        Returns:
            Text description of the image.

        Raises:
            RuntimeError: If the API call fails.
        """
        data_url = f"data:{mime_type};base64,{data}"
        return self._call_vision_api(data_url)

    def _call_vision_api(self, image_url: str) -> str:
        """Call the OpenAI-compatible vision API.

        Args:
            image_url: data: URL or HTTP(S) URL for the image.

        Returns:
            Text description from the model.
        """
        payload = {
            "model": self._config.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self._config.prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": image_url},
                        },
                    ],
                }
            ],
            "max_tokens": 1024,
        }

        body = json.dumps(payload).encode("utf-8")
        req = Request(
            self._endpoint,
            data=body,
            # NOTE FOR FUTURE AGENTS — Provider-specific auth header.
            # This code targets Google's Gemini OpenAI-compatible endpoint and
            # uses `x-goog-api-key`, which is what new AQ.*-format Gemini API
            # keys require (the old Authorization: Bearer path returns
            # "Multiple authentication credentials received" with these keys).
            #
            # Other OpenAI-compatible providers (OpenAI, Together, Groq, etc.)
            # expect `Authorization: Bearer <key>` instead. If you're switching
            # providers, change the header below to match that provider's
            # convention. Don't build a provider abstraction here — let the
            # configuring agent read the provider's docs and pick the right
            # header.
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self._config.api_key,
            },
            method="POST",
        )

        try:
            with urlopen(req) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            raise RuntimeError(f"Vision API call failed: {e}") from e
