"""High-level client for the Ariadne Core REST API.

Wraps the endpoints documented in SPEC.md. Uses stdlib-only transport
via _http.py. Returns dataclass models from models.py and raises the
exceptions from exceptions.py.

Authentication (post-xft.5.5)
-----------------------------
The client is Bearer-JWT only. Every request carries
``Authorization: Bearer <jwt>``, where the JWT is minted by
:func:`ariadne_core_client.auth.get_access_token` from the cached
refresh token (stored by ``ariadne login``). There is no X-API-Key
path — the server-side middleware was removed in Pass 2 of
``ariadne--xft``.

Fail-closed-on-IdP posture
~~~~~~~~~~~~~~~~~~~~~~~~~~
If token acquisition fails for any reason (no stored refresh token,
refresh rejected by Auth0, keyring unreachable, etc.) the client
raises :class:`AriadneAuthError` **without issuing any HTTP request**.
There is no unauthenticated fallback, no silent downgrade, and no
reintroduction of legacy API-key behavior. The ``/api/health``
endpoint is the sole exception: it is declared unauth on the server
and the client mirrors that by skipping the Bearer header entirely.

Escape hatch
~~~~~~~~~~~~
Setting ``ARIADNE_ACCESS_TOKEN`` in the environment bypasses the
keyring / refresh path entirely — :func:`auth.get_access_token`
returns the env value directly. Useful for CI and for recovering
from a broken keyring without reinstalling. Tokens are still never
logged or printed.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from ariadne_core_client import _http, auth as _auth
from ariadne_core_client.exceptions import AriadneAuthError, AriadneClientError
from ariadne_core_client.models import (
    AggregateBucket,
    AggregateResponse,
    Collection,
    Document,
    DocumentListPage,
    Health,
    Interaction,
    QuerySchema,
    SearchResponse,
    SearchResult,
    Stats,
)

DEFAULT_INGEST_TIMEOUT = 600  # seconds — embedding a large doc can take 3-5 min


class AriadneClient:
    """Python client for an Ariadne Core server.

    Parameters
    ----------
    host : str | None, optional
        Ariadne server URL, e.g. ``"https://ariadne.example.com"``. If
        ``None`` (the default), :func:`auth.resolve_host` is consulted:
        ``ARIADNE_HOST`` env var, then the contents of
        ``~/.config/ariadne/default`` (written by ``ariadne login``).
        Passing a value explicitly bypasses both.
    agent_type, initiated_by, model, timeout : see ``SPEC.md``.

    Breaking change (xft.5.5)
    -------------------------
    The legacy ``url=`` and ``api_key=`` keyword arguments were
    removed. The client now speaks OAuth 2.1 Bearer JWT exclusively;
    use ``ariadne login`` to populate the keyring, then construct as
    ``AriadneClient()`` or ``AriadneClient(host=...)``.
    """

    def __init__(
        self,
        host: str | None = None,
        *,
        agent_type: str | None = None,
        initiated_by: str | None = None,
        model: str | None = None,
        timeout: int = 60,
    ) -> None:
        try:
            self.host = _auth.resolve_host(host)
        except _auth.AuthError as err:
            # resolve_host failures are configuration errors (no host set
            # anywhere). Map to AriadneAuthError so callers get the
            # single documented exception surface.
            raise AriadneAuthError(str(err)) from err
        self.agent_type = agent_type
        self.initiated_by = initiated_by
        self.model = model
        self.timeout = timeout

    # ------------------------------------------------------------------ helpers

    def _bearer_token(self) -> str:
        """Return a valid JWT for ``Authorization: Bearer``.

        Delegates to :func:`auth.get_access_token`, which honors the
        ``ARIADNE_ACCESS_TOKEN`` env var first, then cached keyring
        tokens, then a refresh via the stored refresh_token.

        Fail-closed: any failure (missing refresh, rejected refresh,
        keyring unreachable) raises :class:`AriadneAuthError`. No
        network request is made by the caller.
        """
        try:
            return _auth.get_access_token(self.host)
        except _auth.AuthError as err:
            raise AriadneAuthError(str(err)) from err
        except _auth.KeyringBackendUnavailable as err:
            # The wrapped message already carries platform-aware
            # recovery guidance; re-raise as our canonical auth error.
            raise AriadneAuthError(str(err)) from err

    def _headers(self, *, authed: bool = True) -> dict[str, str]:
        """Return request headers.

        ``authed=True`` (the default) attaches ``Authorization: Bearer``.
        ``authed=False`` skips the header entirely — used only for
        ``/api/health``, which the server leaves unauth'd by design.
        """
        if not authed:
            return {}
        return {"Authorization": f"Bearer {self._bearer_token()}"}

    def _endpoint(self, path: str, **query: Any) -> str:
        params = {k: v for k, v in query.items() if v is not None}
        if isinstance(params.get("include_deleted"), bool):
            params["include_deleted"] = "true" if params["include_deleted"] else "false"
        if isinstance(params.get("include_chunks"), bool):
            params["include_chunks"] = "true" if params["include_chunks"] else "false"
        if isinstance(params.get("include_interactions"), bool):
            params["include_interactions"] = "true" if params["include_interactions"] else "false"
        if isinstance(params.get("has_warnings"), bool):
            params["has_warnings"] = "true" if params["has_warnings"] else "false"
        if isinstance(params.get("has_source_reference"), bool):
            params["has_source_reference"] = (
                "true" if params["has_source_reference"] else "false"
            )
        qs = urlencode(params) if params else ""
        base = f"{self.host}{path}"
        return f"{base}?{qs}" if qs else base

    def _caller_metadata(
        self,
        *,
        agent_type: str | None = None,
        initiated_by: str | None = None,
        model: str | None = None,
        agent_notes: str | None = None,
        agent_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Merge instance defaults with per-call overrides."""
        out: dict[str, Any] = {}
        at = agent_type if agent_type is not None else self.agent_type
        ib = initiated_by if initiated_by is not None else self.initiated_by
        md = model if model is not None else self.model
        if at is not None:
            out["agent_type"] = at
        if ib is not None:
            out["initiated_by"] = ib
        if md is not None:
            out["model"] = md
        if agent_notes is not None:
            out["agent_notes"] = agent_notes
        if agent_metadata is not None:
            out["agent_metadata"] = agent_metadata
        return out

    @staticmethod
    def _handle_source(
        source: str | None,
        agent_metadata: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Inject `source` into agent_metadata['source_reference'] if provided."""
        if source is None:
            return agent_metadata
        merged = dict(agent_metadata) if agent_metadata else {}
        merged["source_reference"] = source
        return merged

    # ---------------------------------------------------------- parsing helpers

    @staticmethod
    def _parse_interaction(data: dict[str, Any]) -> Interaction:
        return Interaction(
            agent_id=data.get("agent_id"),
            agent_type=data.get("agent_type"),
            model=data.get("model"),
            initiated_by=data.get("initiated_by"),
            agent_notes=data.get("agent_notes"),
            agent_metadata=data.get("agent_metadata"),
            action=data.get("action"),
            was_dedup_skip=bool(data.get("was_dedup_skip", False)),
            created_at=data.get("created_at"),
        )

    @classmethod
    def _parse_document(cls, data: dict[str, Any]) -> Document:
        markdown = data.get("markdown")
        if markdown is None:
            markdown = data.get("content_markdown")
        interactions = [
            cls._parse_interaction(item)
            for item in data.get("interactions", []) or []
            if isinstance(item, dict)
        ]
        return Document(
            document_id=data.get("document_id", "") or "",
            source_file=data.get("source_file", "") or "",
            title=data.get("title"),
            file_type=data.get("file_type"),
            engine=data.get("engine"),
            content_fingerprint=data.get("content_fingerprint"),
            collection=data.get("collection"),
            markdown=markdown,
            chunk_count=int(data.get("chunk_count") or 0),
            was_dedup_skip=bool(data.get("was_dedup_skip", False)),
            warnings=list(data.get("warnings") or []),
            warnings_count=data.get("warnings_count"),
            processing_time_ms=data.get("processing_time_ms"),
            output_tokens_estimate=data.get("output_tokens_estimate"),
            token_savings_ratio=data.get("token_savings_ratio"),
            token_savings=data.get("token_savings"),
            embedding_model=data.get("embedding_model"),
            store_status=data.get("store_status"),
            interactions=interactions,
            provenance=data.get("provenance"),
            tags=list(data.get("tags") or []),
            interaction_count=data.get("interaction_count"),
            created_at=data.get("created_at"),
        )

    @classmethod
    def _parse_search_result(cls, data: dict[str, Any]) -> SearchResult:
        interactions = [
            cls._parse_interaction(item)
            for item in data.get("interactions", []) or []
            if isinstance(item, dict)
        ]
        return SearchResult(
            chunk_id=data.get("chunk_id", "") or "",
            document_id=data.get("document_id", "") or "",
            collection=data.get("collection"),
            text=data.get("text", "") or "",
            section=data.get("section"),
            page=data.get("page"),
            token_count=int(data.get("token_count") or 0),
            relevance_score=float(data.get("relevance_score") or 0.0),
            embedding_model=data.get("embedding_model"),
            interactions=interactions,
        )

    @staticmethod
    def _parse_collection(data: dict[str, Any]) -> Collection:
        return Collection(
            name=data.get("name", "") or "",
            description=data.get("description"),
            document_count=int(data.get("document_count") or 0),
        )

    # ------------------------------------------------------------- upload util

    def _upload(self, path: Path) -> dict[str, Any]:
        response = _http.multipart_upload(
            self._endpoint("/api/upload"),
            headers=self._headers(),
            filepath=path,
            field_name="file",
            timeout=max(self.timeout, 120),
        )
        if not isinstance(response, dict) or "path" not in response:
            raise AriadneClientError(
                "Upload response missing 'path' field",
                request_info=f"POST {self.host}/api/upload",
            )
        return response

    def _create_document(
        self,
        *,
        uri: str,
        collection: str,
        tags: list[str] | None,
        agent_notes: str | None,
        agent_metadata: dict[str, Any] | None,
        chunking_config: dict[str, Any] | None,
        force: bool,
        timeout: int | None = None,
    ) -> Document:
        body: dict[str, Any] = {
            "uri": uri,
            "collection": collection,
            "force": force,
        }
        if tags:
            body["tags"] = list(tags)
        if chunking_config is not None:
            body["chunking_config"] = chunking_config
        body.update(
            self._caller_metadata(
                agent_notes=agent_notes,
                agent_metadata=agent_metadata,
            )
        )
        effective_timeout = (
            timeout if timeout is not None else max(self.timeout, DEFAULT_INGEST_TIMEOUT)
        )
        response = _http.json_request(
            "POST",
            self._endpoint("/api/documents"),
            headers=self._headers(),
            json_body=body,
            timeout=effective_timeout,
        )
        if not isinstance(response, dict):
            raise AriadneClientError(
                "Ingest response was not a JSON object",
                request_info=f"POST {self.host}/api/documents",
            )
        return self._parse_document(response)

    # ======================================================== public methods

    def health(self) -> Health:
        response = _http.json_request(
            "GET",
            self._endpoint("/api/health"),
            headers=self._headers(authed=False),
            timeout=self.timeout,
        )
        data = response if isinstance(response, dict) else {}
        return Health(
            status=data.get("status", "") or "",
            version=data.get("version", "") or "",
            engine=data.get("engine", "") or "",
            embedding_enabled=bool(data.get("embedding_enabled", False)),
        )

    def ingest_url(
        self,
        url: str,
        *,
        collection: str = "default",
        tags: list[str] | None = None,
        source: str | None = None,
        agent_notes: str | None = None,
        agent_metadata: dict[str, Any] | None = None,
        chunking_config: dict[str, Any] | None = None,
        force: bool = False,
        timeout: int | None = None,
    ) -> Document:
        effective_source = source if source is not None else url
        merged_metadata = self._handle_source(effective_source, agent_metadata)
        return self._create_document(
            uri=url,
            collection=collection,
            tags=tags,
            agent_notes=agent_notes,
            agent_metadata=merged_metadata,
            chunking_config=chunking_config,
            force=force,
            timeout=timeout,
        )

    def ingest_file(
        self,
        path: str | os.PathLike[str],
        *,
        collection: str = "default",
        tags: list[str] | None = None,
        source: str | None = None,
        agent_notes: str | None = None,
        agent_metadata: dict[str, Any] | None = None,
        chunking_config: dict[str, Any] | None = None,
        force: bool = False,
        timeout: int | None = None,
    ) -> Document:
        local_path = Path(path)
        if not local_path.is_file():
            raise AriadneClientError(f"File not found: {local_path}")
        upload = self._upload(local_path)
        merged_metadata = self._handle_source(source, agent_metadata)
        return self._create_document(
            uri=upload["path"],
            collection=collection,
            tags=tags,
            agent_notes=agent_notes,
            agent_metadata=merged_metadata,
            chunking_config=chunking_config,
            force=force,
            timeout=timeout,
        )

    def ingest_bytes(
        self,
        content: bytes,
        filename: str,
        *,
        collection: str = "default",
        tags: list[str] | None = None,
        source: str | None = None,
        agent_notes: str | None = None,
        agent_metadata: dict[str, Any] | None = None,
        chunking_config: dict[str, Any] | None = None,
        force: bool = False,
        timeout: int | None = None,
    ) -> Document:
        if not isinstance(content, (bytes, bytearray)):
            raise AriadneClientError("ingest_bytes requires bytes content")
        safe_name = Path(filename).name or "upload.bin"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / safe_name
            tmp_path.write_bytes(bytes(content))
            upload = self._upload(tmp_path)
        merged_metadata = self._handle_source(source, agent_metadata)
        return self._create_document(
            uri=upload["path"],
            collection=collection,
            tags=tags,
            agent_notes=agent_notes,
            agent_metadata=merged_metadata,
            chunking_config=chunking_config,
            force=force,
            timeout=timeout,
        )

    def search(
        self,
        query: str,
        *,
        collection: str | None = None,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
        include_deleted: bool = False,
        agent_notes: str | None = None,
        agent_metadata: dict[str, Any] | None = None,
    ) -> SearchResponse:
        body: dict[str, Any] = {
            "query": query,
            "top_k": top_k,
            "include_deleted": include_deleted,
        }
        if collection is not None:
            body["collection"] = collection
        if filters is not None:
            body["filters"] = filters
        body.update(
            self._caller_metadata(
                agent_notes=agent_notes,
                agent_metadata=agent_metadata,
            )
        )
        response = _http.json_request(
            "POST",
            self._endpoint("/api/search"),
            headers=self._headers(),
            json_body=body,
            timeout=self.timeout,
        )
        data = response if isinstance(response, dict) else {}
        results = [
            self._parse_search_result(item)
            for item in data.get("results") or []
            if isinstance(item, dict)
        ]
        return SearchResponse(
            query=data.get("query", query) or query,
            top_k=int(data.get("top_k") or top_k),
            collection=data.get("collection"),
            results_count=int(data.get("results_count") or len(results)),
            results=results,
        )

    def get_document(
        self,
        document_id: str,
        *,
        include_chunks: bool = True,
        include_interactions: bool = True,
    ) -> Document:
        response = _http.json_request(
            "GET",
            self._endpoint(
                f"/api/documents/{quote(document_id, safe='')}",
                include_chunks=include_chunks,
                include_interactions=include_interactions,
            ),
            headers=self._headers(),
            timeout=self.timeout,
        )
        if not isinstance(response, dict):
            raise AriadneClientError(
                "get_document response was not a JSON object",
                request_info=f"GET {self.host}/api/documents/{document_id}",
            )
        return self._parse_document(response)

    def list_documents(
        self,
        *,
        collection: str | None = None,
        file_type: str | None = None,
        tag: str | None = None,
        has_warnings: bool | None = None,
        has_source_reference: bool | None = None,
        include: list[str] | None = None,
        limit: int = 20,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> DocumentListPage:
        """List documents on the server, with filters + projection.

        Args:
            collection: exact collection name.
            file_type: exact file type (leading dot stripped
                server-side).
            tag: docs whose tag list contains this tag. Single-value
                only — the server ANDs nothing, it just matches one.
            has_warnings: True = only docs with >=1 warning; False =
                only clean docs; None = both.
            has_source_reference: True = latest interaction's
                agent_metadata has a non-empty, non-"unknown"
                source_reference; False = inverse; None = both.
            include: list of extra row fields to request. Accepts
                any of: "agent_metadata", "tags", "last_interaction",
                "markdown". Server caps limit at 50 when "markdown"
                is in this list, 500 otherwise.
            limit: page size (default 20).
            offset: page offset (default 0).
            include_deleted: include soft-deleted docs (default False).

        Returns:
            A `DocumentListPage` with `.documents`, `.total_count`,
            `.total_is_exact`, `.limit`, `.offset`. Iterable as a list
            of `Document`.

        Raises:
            AriadneClientError: on non-dict response or server 4xx/5xx.
        """
        params: dict[str, Any] = {
            "collection": collection,
            "file_type": file_type,
            "tag": tag,
            "has_warnings": has_warnings,
            "has_source_reference": has_source_reference,
            "limit": limit,
            "offset": offset,
            "include_deleted": include_deleted,
        }
        base = self._endpoint("/api/documents", **params)
        if include:
            from urllib.parse import urlencode as _ue
            sep = "&" if "?" in base else "?"
            base = f"{base}{sep}{_ue([('include', v) for v in include])}"

        response = _http.json_request(
            "GET",
            base,
            headers=self._headers(),
            timeout=self.timeout,
        )
        data = response if isinstance(response, dict) else {}
        return DocumentListPage(
            documents=[
                self._parse_document(item)
                for item in data.get("documents") or []
                if isinstance(item, dict)
            ],
            total_count=int(data.get("total_count") or 0),
            total_is_exact=bool(data.get("total_is_exact", True)),
            limit=int(data.get("limit") or limit),
            offset=int(data.get("offset") or offset),
        )

    def aggregate(
        self,
        group_by: str,
        *,
        collection: str | None = None,
        file_type: str | None = None,
        tag: str | None = None,
        has_warnings: bool | None = None,
        has_source_reference: bool | None = None,
        include_deleted: bool = False,
    ) -> AggregateResponse:
        """Group-by count over /api/documents filters.

        Args:
            group_by: one of "collection", "file_type", "tags".
                Call `self.schema()` for the current list.
            collection, file_type, tag, has_warnings,
            has_source_reference, include_deleted: same semantics as
                `list_documents`. Applied as a WHERE clause before
                grouping.

        Returns:
            An `AggregateResponse`. Iterates as a list of
            `AggregateBucket`.

        Raises:
            AriadneClientError: on non-dict response or server 4xx
                (e.g. unknown `group_by` returns a structured 400 with
                the valid list; that surfaces as an AriadneClientError
                with the error detail).
        """
        params: dict[str, Any] = {
            "group_by": group_by,
            "collection": collection,
            "file_type": file_type,
            "tag": tag,
            "has_warnings": has_warnings,
            "has_source_reference": has_source_reference,
            "include_deleted": include_deleted,
        }
        response = _http.json_request(
            "GET",
            self._endpoint("/api/documents/aggregate", **params),
            headers=self._headers(),
            timeout=self.timeout,
        )
        if not isinstance(response, dict):
            raise AriadneClientError(
                "aggregate response was not a JSON object",
                request_info=f"GET {self.host}/api/documents/aggregate",
            )
        return AggregateResponse(
            group_by=response.get("group_by", "") or "",
            filters=dict(response.get("filters") or {}),
            buckets=[
                AggregateBucket(
                    group=b.get("group"),
                    count=int(b.get("count") or 0),
                )
                for b in response.get("buckets") or []
                if isinstance(b, dict)
            ],
            total_buckets=int(response.get("total_buckets") or 0),
            total_documents=int(response.get("total_documents") or 0),
        )

    def schema(self) -> QuerySchema:
        """Fetch the query-surface discovery document.

        Call this first from an agent to learn what filters, includes,
        and aggregatable fields are available on this server.

        Returns:
            A `QuerySchema` with per-server filter / include /
            aggregatable-field registries and caps.
        """
        response = _http.json_request(
            "GET",
            self._endpoint("/api/documents/schema"),
            headers=self._headers(),
            timeout=self.timeout,
        )
        if not isinstance(response, dict):
            raise AriadneClientError(
                "schema response was not a JSON object",
                request_info=f"GET {self.host}/api/documents/schema",
            )
        return QuerySchema(
            list_endpoint=response.get("list_endpoint", "") or "",
            aggregate_endpoint=(
                response.get("aggregate_endpoint", "") or ""
            ),
            filters=dict(response.get("filters") or {}),
            includes=dict(response.get("includes") or {}),
            aggregatable_fields=dict(
                response.get("aggregatable_fields") or {}
            ),
            caps=dict(response.get("caps") or {}),
            brute_force_fallback=(
                response.get("brute_force_fallback", "") or ""
            ),
            deferred=dict(response.get("deferred") or {}),
        )

    def list_collections(self) -> list[Collection]:
        response = _http.json_request(
            "GET",
            self._endpoint("/api/collections"),
            headers=self._headers(),
            timeout=self.timeout,
        )
        data = response if isinstance(response, dict) else {}
        return [
            self._parse_collection(item)
            for item in data.get("collections") or []
            if isinstance(item, dict)
        ]

    def create_collection(
        self,
        name: str,
        *,
        description: str | None = None,
    ) -> Collection:
        body: dict[str, Any] = {"name": name}
        if description is not None:
            body["description"] = description
        if self.initiated_by is not None:
            body["initiated_by"] = self.initiated_by
        response = _http.json_request(
            "POST",
            self._endpoint("/api/collections"),
            headers=self._headers(),
            json_body=body,
            timeout=self.timeout,
        )
        data = response if isinstance(response, dict) else {}
        return Collection(
            name=data.get("name", name) or name,
            description=data.get("description", description),
            document_count=int(data.get("document_count") or 0),
        )

    def update_document(
        self,
        document_id: str,
        *,
        tags: list[str] | None = None,
        collection: str | None = None,
        agent_metadata: dict[str, Any] | None = None,
        agent_notes: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if tags is not None:
            body["tags"] = list(tags)
        if collection is not None:
            body["collection"] = collection
        body.update(
            self._caller_metadata(
                agent_notes=agent_notes,
                agent_metadata=agent_metadata,
            )
        )
        response = _http.json_request(
            "PATCH",
            self._endpoint(f"/api/documents/{quote(document_id, safe='')}"),
            headers=self._headers(),
            json_body=body,
            timeout=self.timeout,
        )
        return response if isinstance(response, dict) else {}

    def delete_document(
        self,
        document_id: str,
        *,
        agent_notes: str | None = None,
    ) -> dict[str, Any]:
        body = self._caller_metadata(agent_notes=agent_notes)
        response = _http.json_request(
            "DELETE",
            self._endpoint(f"/api/documents/{quote(document_id, safe='')}"),
            headers=self._headers(),
            json_body=body or None,
            timeout=self.timeout,
        )
        return response if isinstance(response, dict) else {}

    def restore_document(
        self,
        document_id: str,
        *,
        agent_notes: str | None = None,
    ) -> dict[str, Any]:
        body = self._caller_metadata(agent_notes=agent_notes)
        response = _http.json_request(
            "POST",
            self._endpoint(f"/api/documents/{quote(document_id, safe='')}/restore"),
            headers=self._headers(),
            json_body=body or None,
            timeout=self.timeout,
        )
        return response if isinstance(response, dict) else {}

    def delete_collection(
        self,
        name: str,
        *,
        agent_notes: str | None = None,
    ) -> dict[str, Any]:
        body = self._caller_metadata(agent_notes=agent_notes)
        response = _http.json_request(
            "DELETE",
            self._endpoint(f"/api/collections/{quote(name, safe='')}"),
            headers=self._headers(),
            json_body=body or None,
            timeout=self.timeout,
        )
        return response if isinstance(response, dict) else {}

    def restore_collection(
        self,
        name: str,
        *,
        agent_notes: str | None = None,
    ) -> dict[str, Any]:
        body = self._caller_metadata(agent_notes=agent_notes)
        response = _http.json_request(
            "POST",
            self._endpoint(f"/api/collections/{quote(name, safe='')}/restore"),
            headers=self._headers(),
            json_body=body or None,
            timeout=self.timeout,
        )
        return response if isinstance(response, dict) else {}

    def stats(self) -> Stats:
        response = _http.json_request(
            "GET",
            self._endpoint("/api/stats"),
            headers=self._headers(),
            timeout=self.timeout,
        )
        data = response if isinstance(response, dict) else {}
        collections = data.get("collections") or {}
        if not isinstance(collections, dict):
            collections = {}
        return Stats(
            total_documents=int(data.get("total_documents") or 0),
            total_chunks=int(data.get("total_chunks") or 0),
            total_collections=int(data.get("total_collections") or 0),
            embedding_enabled=bool(data.get("embedding_enabled", False)),
            collections={str(k): int(v or 0) for k, v in collections.items()},
        )
