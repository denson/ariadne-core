"""Embedding API client — any OpenAI-compatible endpoint.

Sends text chunks to an embedding model and returns vectors.
Supports OpenAI, Together, Groq, or any endpoint that accepts
the OpenAI embeddings API format.

If no API key is configured, the embedder is disabled and chunks
are stored without embeddings (search will not work).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingConfig:
    """Configuration for the embedding API client."""

    model: str = "text-embedding-3-small"
    dimensions: int = 1536
    provider: str = "openai-compatible"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""


@dataclass
class EmbeddingResult:
    """Result of embedding a batch of texts."""

    embeddings: list[list[float]]
    model: str
    total_tokens: int
    processing_time_ms: int
    processing_chain_entry: dict[str, Any]


class EmbeddingClient:
    """Client for generating embeddings via an OpenAI-compatible API."""

    def __init__(self, config: EmbeddingConfig | None = None) -> None:
        self._config = config
        self._endpoint = (
            f"{config.base_url.rstrip('/')}/embeddings" if config else ""
        )

    @property
    def enabled(self) -> bool:
        return self._config is not None and bool(self._config.api_key)

    @property
    def model(self) -> str:
        return self._config.model if self._config else ""

    @property
    def dimensions(self) -> int:
        return self._config.dimensions if self._config else 0

    def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        """Embed a batch of texts.

        Args:
            texts: List of text strings to embed.

        Returns:
            EmbeddingResult with embedding vectors and metadata.

        Raises:
            RuntimeError: If the API call fails or client is disabled.
        """
        if not self.enabled:
            raise RuntimeError("Embedding client is not configured (no API key)")

        if not texts:
            return EmbeddingResult(
                embeddings=[],
                model=self.model,
                total_tokens=0,
                processing_time_ms=0,
                processing_chain_entry={},
            )

        start = time.perf_counter()
        assert self._config is not None

        payload: dict[str, Any] = {
            "model": self._config.model,
            "input": texts,
        }

        body = json.dumps(payload).encode("utf-8")
        req = Request(
            self._endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._config.api_key}",
            },
            method="POST",
        )

        try:
            with urlopen(req) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            # Drain the response body so we actually see Google's / OpenAI's
            # error message, not just "HTTP Error 400: Bad Request".
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                err_body = "<could not read response body>"
            logger.error(
                "Embedding API call failed: status=%s endpoint=%s model=%s "
                "dimensions=%s batch_size=%d response_body=%s",
                e.code,
                self._endpoint,
                self._config.model,
                self._config.dimensions,
                len(texts),
                err_body,
            )
            raise RuntimeError(
                f"Embedding API call failed: HTTP {e.code} from "
                f"{self._endpoint} (model={self._config.model}): {err_body}"
            ) from e
        except URLError as e:
            logger.error(
                "Embedding API call failed (network/URL): endpoint=%s "
                "model=%s reason=%s",
                self._endpoint,
                self._config.model,
                e.reason,
            )
            raise RuntimeError(
                f"Embedding API call failed ({self._endpoint}): {e.reason}"
            ) from e
        except Exception as e:
            logger.exception(
                "Embedding API call failed unexpectedly: endpoint=%s model=%s",
                self._endpoint,
                self._config.model,
            )
            raise RuntimeError(f"Embedding API call failed: {e}") from e

        # Extract embeddings in order
        data = sorted(result["data"], key=lambda x: x["index"])
        embeddings = [item["embedding"] for item in data]

        total_tokens = result.get("usage", {}).get("total_tokens", 0)
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        chain_entry = {
            "step": "embedding",
            "tool": f"openai:{self._config.model}",
            "ts": datetime.now(timezone.utc).isoformat(),
            "ms": elapsed_ms,
            "chunks_embedded": len(texts),
            "total_tokens": total_tokens,
        }

        return EmbeddingResult(
            embeddings=embeddings,
            model=self._config.model,
            total_tokens=total_tokens,
            processing_time_ms=elapsed_ms,
            processing_chain_entry=chain_entry,
        )

    def embed_query(self, query: str) -> list[float]:
        """Embed a single query string.

        Args:
            query: The query text to embed.

        Returns:
            Embedding vector as a list of floats.

        Raises:
            RuntimeError: If the API call fails or client is disabled.
        """
        result = self.embed_texts([query])
        return result.embeddings[0]
