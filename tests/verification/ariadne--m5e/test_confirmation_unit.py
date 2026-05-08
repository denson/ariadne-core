"""Unit-tier probes for the HMAC confirmation primitive (m5e §4 unit extras).

Covers the contract of pipeline.api.confirmation in isolation from the
ingest pipeline:

  * round-trip: issue then validate yields VALID
  * HMAC bypass: wrong sig → TAMPERED
  * expired token → EXPIRED
  * URI mismatch → URI_MISMATCH
  * malformed token shapes → TAMPERED
  * configure_ingest cap-coherence + TTL validators
  * autouse confirmation-secret isolation works (test 1 mutates;
    test 2 sees the restored value)
  * Nit 6 default-permissive: token without ``size_precise`` field
    validates to VALID

Pinned in design-rev3.1 §4 unit-tier extras + §11.A.6.
"""
from __future__ import annotations

import base64
import hmac
import json
import time
from hashlib import sha256

import pytest

from pipeline.api import confirmation as conf
from pipeline.api.confirmation import (
    ValidationResult,
    configure_confirmation,
    issue_token,
    validate_token,
)
from pipeline.config import IngestConfig
from pipeline.services import configure_ingest


# ── Round-trip + HMAC bypass ────────────────────────────────────────────────


def test_round_trip_returns_valid():
    token, exp = issue_token(
        source_uri="https://example.org/big.pdf",
        reported_size=300_000_000,
        size_precise=True,
        ttl_seconds=300,
    )
    assert validate_token(
        token, source_uri="https://example.org/big.pdf"
    ) == ValidationResult.VALID
    # exp is roughly now + 300; allow a 10s slack.
    assert exp - int(time.time()) <= 300
    assert exp - int(time.time()) >= 290


def test_hmac_mismatch_returns_tampered():
    token, _ = issue_token(
        source_uri="https://example.org/big.pdf",
        reported_size=300_000_000,
        size_precise=True,
        ttl_seconds=300,
    )
    payload_part, _sig = token.split(".", 1)
    # Replace signature with valid base64url that will not match.
    bogus_sig = base64.urlsafe_b64encode(b"\x00" * 32).rstrip(b"=").decode()
    tampered = f"{payload_part}.{bogus_sig}"
    assert validate_token(
        tampered, source_uri="https://example.org/big.pdf"
    ) == ValidationResult.TAMPERED


def test_empty_signature_returns_tampered():
    token, _ = issue_token(
        source_uri="https://example.org/big.pdf",
        reported_size=300_000_000,
        size_precise=True,
        ttl_seconds=300,
    )
    payload_part, _sig = token.split(".", 1)
    tampered = f"{payload_part}."
    assert validate_token(
        tampered, source_uri="https://example.org/big.pdf"
    ) == ValidationResult.TAMPERED


def test_no_dot_returns_tampered():
    assert validate_token(
        "no-dot-here", source_uri="https://example.org/x"
    ) == ValidationResult.TAMPERED


def test_bogus_base64_returns_tampered():
    assert validate_token(
        "@@@.@@@", source_uri="https://example.org/x"
    ) == ValidationResult.TAMPERED


# ── exp / URI checks ────────────────────────────────────────────────────────


def test_expired_token_returns_expired(monkeypatch):
    token, exp = issue_token(
        source_uri="https://example.org/big.pdf",
        reported_size=1,
        size_precise=True,
        ttl_seconds=2,
    )
    # Advance clock past exp.
    monkeypatch.setattr(conf.time, "time", lambda: exp + 1)
    assert validate_token(
        token, source_uri="https://example.org/big.pdf"
    ) == ValidationResult.EXPIRED


def test_uri_mismatch_returns_uri_mismatch():
    token, _ = issue_token(
        source_uri="https://example.org/A.pdf",
        reported_size=1,
        size_precise=True,
        ttl_seconds=300,
    )
    assert validate_token(
        token, source_uri="https://example.org/B.pdf"
    ) == ValidationResult.URI_MISMATCH


# ── Default-permissive size_precise (Nit 6) ─────────────────────────────────


def test_token_without_size_precise_field_validates(monkeypatch):
    """Hand-craft a token whose payload omits ``size_precise``; assert
    validate_token returns VALID. Pins the rev3 §11.A.6 default-permissive
    pick — a future rotation to TAMPERED-on-missing surfaces here as a
    probe failure rather than a silent regression."""
    # Hand-craft a token using the autouse-installed test secret.
    payload = {
        "v": 1,
        "uri": "https://example.org/x",
        "size": 999,
        # NOTE: deliberately no size_precise field.
        "exp": int(time.time()) + 60,
    }
    payload_bytes = json.dumps(
        payload, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    sig = hmac.new(
        conf._CONFIRMATION_SECRET, payload_bytes, sha256
    ).digest()
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    token = f"{payload_b64}.{sig_b64}"

    assert validate_token(
        token, source_uri="https://example.org/x"
    ) == ValidationResult.VALID


def test_token_with_wrong_version_returns_tampered():
    """Future-proof: a token with ``v != 1`` is rejected as TAMPERED."""
    payload = {
        "v": 99,
        "uri": "https://example.org/x",
        "size": 1,
        "size_precise": True,
        "exp": int(time.time()) + 60,
    }
    payload_bytes = json.dumps(
        payload, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    sig = hmac.new(conf._CONFIRMATION_SECRET, payload_bytes, sha256).digest()
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    token = f"{payload_b64}.{sig_b64}"

    assert validate_token(
        token, source_uri="https://example.org/x"
    ) == ValidationResult.TAMPERED


def test_token_missing_required_field_returns_tampered():
    """Missing ``size`` key (or ``uri``, or ``exp``) → TAMPERED."""
    payload = {
        "v": 1,
        "uri": "https://example.org/x",
        # no "size"
        "size_precise": True,
        "exp": int(time.time()) + 60,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(conf._CONFIRMATION_SECRET, payload_bytes, sha256).digest()
    token = (
        base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()
        + "."
        + base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    )

    assert validate_token(
        token, source_uri="https://example.org/x"
    ) == ValidationResult.TAMPERED


# ── configure_ingest validators (m5e new) ───────────────────────────────────


def test_configure_ingest_rejects_hard_below_soft():
    with pytest.raises(ValueError) as excinfo:
        configure_ingest(IngestConfig(
            max_source_bytes=1024,
            max_source_bytes_hard=512,
        ))
    msg = str(excinfo.value)
    assert "max_source_bytes_hard" in msg and "max_source_bytes" in msg


def test_configure_ingest_rejects_zero_ttl():
    with pytest.raises(ValueError) as excinfo:
        configure_ingest(IngestConfig(
            max_source_bytes=1024,
            max_source_bytes_hard=2048,
            confirmation_token_ttl_seconds=0,
        ))
    assert "confirmation_token_ttl_seconds" in str(excinfo.value)


def test_configure_ingest_rejects_negative_ttl():
    with pytest.raises(ValueError):
        configure_ingest(IngestConfig(
            max_source_bytes=1024,
            max_source_bytes_hard=2048,
            confirmation_token_ttl_seconds=-1,
        ))


def test_configure_ingest_accepts_hard_equal_to_soft():
    """Edge case: hard == soft is coherent (the confirmation flow
    triggers at soft and immediately the hard check fires; but since
    ``size >= effective_hard`` check comes first in the dispatch, the
    deployment is effectively strict-mode for sizes >= soft). Allowed."""
    configure_ingest(IngestConfig(
        max_source_bytes=1024,
        max_source_bytes_hard=1024,
    ))


# ── Autouse fixture isolation (rev2) ────────────────────────────────────────
#
# Two consecutive tests where test 1 mutates the secret to b"value-A"
# and test 2 asserts the secret has been restored to the test default.
# Confirms cross-test isolation. The fixture lives in tests/conftest.py.


_FIXTURE_DEFAULT = b"test-secret-do-not-ship"


def test_autouse_fixture_is_active():
    """The autouse fixture installed the deterministic test secret."""
    assert conf._CONFIRMATION_SECRET == _FIXTURE_DEFAULT


def test_autouse_isolation_step1_mutates_secret():
    """Mutate the secret mid-test; the fixture's teardown will restore
    the deterministic default before the next test runs."""
    configure_confirmation(secret=b"value-A-only-for-this-test")
    assert conf._CONFIRMATION_SECRET == b"value-A-only-for-this-test"


def test_autouse_isolation_step2_secret_restored():
    """Subsequent test must see the restored deterministic default,
    NOT the previous test's mutated value."""
    assert conf._CONFIRMATION_SECRET == _FIXTURE_DEFAULT


# ── validate_token before configure_confirmation (defensive) ────────────────


def test_validate_token_before_configure_returns_tampered(monkeypatch):
    """Defensive shape — if validate is somehow called before configure,
    every token returns TAMPERED rather than raising."""
    monkeypatch.setattr(conf, "_CONFIRMATION_SECRET", None)
    assert validate_token(
        "anything.anything", source_uri="https://example.org/x"
    ) == ValidationResult.TAMPERED


def test_issue_token_before_configure_raises(monkeypatch):
    """Defensive shape — issue_token raises rather than silently issuing
    with a None secret."""
    monkeypatch.setattr(conf, "_CONFIRMATION_SECRET", None)
    with pytest.raises(RuntimeError):
        issue_token(
            source_uri="https://example.org/x",
            reported_size=1,
            size_precise=True,
            ttl_seconds=300,
        )
