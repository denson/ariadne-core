"""Unauthenticated `.well-known` discovery endpoints.

Exposes `GET /.well-known/ariadne-config`, which tells a client (an
Ariadne CLI or any agent runtime) how to authenticate against this
server. The client fetches this once at login time, then runs the
Auth0 PKCE flow with the returned `issuer` / `client_id` / `audience` /
`scope` values.

The endpoint is mounted at the app root (not under `/api`), matching
the convention that `.well-known/*` is namespaced per host, not per
API prefix.

This router is intentionally separate from `pipeline.api.routes` so
its mount path and auth posture (open, no dependency) are obvious at
the include-router site. Do NOT add `Depends(require_user)` to the
discovery endpoint — a client that can't auth yet needs to be able to
read it, by definition.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/.well-known/ariadne-config")
async def ariadne_config() -> dict:
    """Return the Auth0 OAuth config a client needs to run the login flow.

    Shape (locked in OAUTH_PLAN.md, ariadne--xft.2 brief):

        {
          "auth": {
            "issuer":    "https://<domain>/",          # trailing slash
            "client_id": "<native app client id>",
            "audience":  "<api audience identifier>",
            "scope":     "openid profile email offline_access"
          }
        }

    `offline_access` is what makes Auth0 issue a refresh token alongside
    the access token — the client caches the refresh token in the OS
    keyring and exchanges it for fresh access tokens without user
    interaction (see OAUTH_PLAN.md Pass 3).

    If `AUTH0_DOMAIN` / `AUTH0_CLIENT_ID` / `AUTH0_AUDIENCE` are unset
    at request time, we return 500 with `auth_misconfigured` — the
    same server-misconfiguration signal we use in the Bearer path.
    This endpoint is unauthenticated, so a deploy that forgot to set
    the env vars is caught by the first client GET rather than the
    first authenticated request.
    """
    domain = os.environ.get("AUTH0_DOMAIN")
    client_id = os.environ.get("AUTH0_CLIENT_ID")
    audience = os.environ.get("AUTH0_AUDIENCE")

    if not domain or not client_id or not audience:
        raise HTTPException(status_code=500, detail="auth_misconfigured")

    return {
        "auth": {
            "issuer": f"https://{domain}/",
            "client_id": client_id,
            "audience": audience,
            "scope": "openid profile email offline_access",
        }
    }
