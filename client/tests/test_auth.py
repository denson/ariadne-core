"""Hermetic unit tests for ariadne_core_client.auth.

Layer 1 + 2 coverage per the ticket brief — PKCE maths, KeyringStore
round-trip against an in-memory fake, platform dispatch of the keyring
error templates, CLI host-resolution precedence, and loopback port
fallback. Layer 3 (mock Auth0) and Layer 4 (live loopback server with
a fake callback curl) are VERA's territory.

No network, no real keyring backend, no browser, no live Auth0.
"""

from __future__ import annotations

import base64
import hashlib
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ariadne_core_client import auth


# ========================================================================== PKCE

class TestGeneratePkce:
    def test_verifier_and_challenge_lengths(self) -> None:
        verifier, challenge = auth._generate_pkce()
        # 32 bytes -> token_urlsafe emits 43 chars (no padding).
        assert len(verifier) == 43
        # BASE64URL(SHA256(...)) with padding stripped is 43 chars.
        assert len(challenge) == 43

    def test_verifier_is_rfc7636_charset(self) -> None:
        verifier, _ = auth._generate_pkce()
        # RFC 7636 § 4.1: "unreserved" = [A-Z] / [a-z] / [0-9] / "-" / "." / "_" / "~".
        # token_urlsafe emits [A-Za-z0-9_-]; all of these are in the unreserved set.
        allowed = set(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        )
        assert set(verifier).issubset(allowed), verifier

    def test_challenge_has_no_padding(self) -> None:
        _, challenge = auth._generate_pkce()
        assert "=" not in challenge

    def test_challenge_matches_sha256_of_verifier(self) -> None:
        """The S256 relationship: challenge = BASE64URL(SHA256(verifier))."""
        verifier, challenge = auth._generate_pkce()
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        assert challenge == expected

    def test_successive_calls_are_unique(self) -> None:
        pairs = {auth._generate_pkce() for _ in range(20)}
        assert len(pairs) == 20  # astronomically unlikely collision otherwise

    def test_rfc7636_appendix_b_test_vector(self) -> None:
        """Verify the known-answer S256 example from RFC 7636 Appendix B."""
        verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        assert challenge == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


# ================================================================= state entropy

def test_generate_state_is_high_entropy() -> None:
    state = auth._generate_state()
    # token_urlsafe(32) emits 43 chars; 256 bits of entropy.
    assert len(state) == 43


# ====================================================== KeyringStore round-trip

class TestInMemoryKeyringStore:
    def test_round_trip(self) -> None:
        store = auth.InMemoryKeyringStore()
        assert store.get("https://x.example", auth.SLOT_ACCESS_TOKEN) is None
        store.set("https://x.example", auth.SLOT_ACCESS_TOKEN, "tk-abc")
        assert store.get("https://x.example", auth.SLOT_ACCESS_TOKEN) == "tk-abc"

    def test_host_scoping(self) -> None:
        store = auth.InMemoryKeyringStore()
        store.set("https://a.example", auth.SLOT_REFRESH_TOKEN, "rt-a")
        store.set("https://b.example", auth.SLOT_REFRESH_TOKEN, "rt-b")
        assert store.get("https://a.example", auth.SLOT_REFRESH_TOKEN) == "rt-a"
        assert store.get("https://b.example", auth.SLOT_REFRESH_TOKEN) == "rt-b"

    def test_slot_scoping(self) -> None:
        store = auth.InMemoryKeyringStore()
        store.set("https://x.example", auth.SLOT_ACCESS_TOKEN, "acc")
        store.set("https://x.example", auth.SLOT_REFRESH_TOKEN, "ref")
        assert store.get("https://x.example", auth.SLOT_ACCESS_TOKEN) == "acc"
        assert store.get("https://x.example", auth.SLOT_REFRESH_TOKEN) == "ref"

    def test_delete_idempotent(self) -> None:
        store = auth.InMemoryKeyringStore()
        store.set("https://x.example", auth.SLOT_ACCESS_TOKEN, "x")
        store.delete("https://x.example", auth.SLOT_ACCESS_TOKEN)
        # Second delete must not raise.
        store.delete("https://x.example", auth.SLOT_ACCESS_TOKEN)
        assert store.get("https://x.example", auth.SLOT_ACCESS_TOKEN) is None


# ========================================================= platform error dispatch

class TestFormatKeyringError:
    def test_macos_template(self) -> None:
        msg = auth.format_keyring_error(RuntimeError("kc locked"), platform="darwin")
        assert "macOS Keychain" in msg
        assert "Keychain Access" in msg
        assert "ARIADNE_ACCESS_TOKEN" in msg
        assert "kc locked" in msg
        assert msg.rstrip().endswith("kc locked")

    def test_windows_template(self) -> None:
        msg = auth.format_keyring_error(RuntimeError("no cred mgr"), platform="win32")
        assert "Windows Credential Manager" in msg
        assert "Credential Manager" in msg
        assert "services.msc" in msg
        assert "ARIADNE_ACCESS_TOKEN" in msg
        assert "no cred mgr" in msg

    def test_linux_template_default_fallback(self) -> None:
        msg = auth.format_keyring_error(RuntimeError("no backend"), platform="linux")
        assert "No OS keyring backend" in msg
        assert "gnome-keyring" in msg
        assert "apt install" in msg
        assert "dnf install" in msg
        assert "pacman" in msg
        assert "gnome-keyring-daemon --start" in msg
        assert "ARIADNE_ACCESS_TOKEN" in msg
        assert "no backend" in msg

    def test_unknown_platform_falls_back_to_linux(self) -> None:
        msg = auth.format_keyring_error(RuntimeError("foo"), platform="freebsd13")
        assert "No OS keyring backend" in msg  # Linux template is the fallback

    def test_exception_with_empty_str_uses_class_name(self) -> None:
        class EmptyExc(Exception):
            def __str__(self) -> str:
                return ""

        msg = auth.format_keyring_error(EmptyExc(), platform="linux")
        assert "EmptyExc" in msg


# =============================================================== resolve_host

class TestResolveHost:
    def test_flag_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = tmp_path / "default"
        cfg.write_text("https://file.example\n", encoding="utf-8")
        monkeypatch.setenv("ARIADNE_HOST", "https://env.example")
        got = auth.resolve_host(
            "https://flag.example",
            env={"ARIADNE_HOST": "https://env.example"},
            config_path=cfg,
        )
        assert got == "https://flag.example"

    def test_env_beats_file(self, tmp_path: Path) -> None:
        cfg = tmp_path / "default"
        cfg.write_text("https://file.example\n", encoding="utf-8")
        got = auth.resolve_host(
            None,
            env={"ARIADNE_HOST": "https://env.example"},
            config_path=cfg,
        )
        assert got == "https://env.example"

    def test_file_used_when_no_flag_no_env(self, tmp_path: Path) -> None:
        cfg = tmp_path / "default"
        cfg.write_text("https://file.example\n", encoding="utf-8")
        got = auth.resolve_host(None, env={}, config_path=cfg)
        assert got == "https://file.example"

    def test_trailing_slashes_stripped(self, tmp_path: Path) -> None:
        got = auth.resolve_host("https://x.example///", env={}, config_path=tmp_path / "nope")
        assert got == "https://x.example"

    def test_missing_file_is_not_fatal_until_all_sources_exhausted(self, tmp_path: Path) -> None:
        got = auth.resolve_host(
            None,
            env={"ARIADNE_HOST": "https://env.example"},
            config_path=tmp_path / "absent",
        )
        assert got == "https://env.example"

    def test_empty_file_falls_through_to_error(self, tmp_path: Path) -> None:
        cfg = tmp_path / "default"
        cfg.write_text("", encoding="utf-8")
        with pytest.raises(auth.AuthError) as exc:
            auth.resolve_host(None, env={}, config_path=cfg)
        assert "--host" in str(exc.value)
        assert "ARIADNE_HOST" in str(exc.value)

    def test_all_empty_raises(self, tmp_path: Path) -> None:
        with pytest.raises(auth.AuthError):
            auth.resolve_host(None, env={}, config_path=tmp_path / "nope")

    def test_file_with_trailing_whitespace(self, tmp_path: Path) -> None:
        cfg = tmp_path / "default"
        cfg.write_text("  https://file.example/  \n", encoding="utf-8")
        got = auth.resolve_host(None, env={}, config_path=cfg)
        assert got == "https://file.example"


class TestWriteDefaultHost:
    def test_write_creates_parent_and_file(self, tmp_path: Path) -> None:
        target = tmp_path / "sub" / "dir" / "default"
        auth.write_default_host("https://x.example", config_path=target)
        assert target.read_text(encoding="utf-8") == "https://x.example"

    def test_write_overwrites_unconditionally(self, tmp_path: Path) -> None:
        target = tmp_path / "default"
        target.write_text("https://old.example", encoding="utf-8")
        auth.write_default_host("https://new.example", config_path=target)
        assert target.read_text(encoding="utf-8") == "https://new.example"


# ================================================================= port fallback

class TestFindFreeLoopbackPort:
    def test_returns_first_free_port(self) -> None:
        # Pick a range of high-numbered ports unlikely to collide; the
        # production list is 8765-8769 but we don't want the tests to
        # depend on what the developer has running.
        port = auth._find_free_loopback_port([49301, 49302, 49303])
        assert port == 49301

    def test_falls_through_when_first_busy(self) -> None:
        # Occupy 49311; the function should advance to 49312.
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blocker.bind(("127.0.0.1", 49311))
        blocker.listen(1)
        try:
            port = auth._find_free_loopback_port([49311, 49312])
            assert port == 49312
        finally:
            blocker.close()

    def test_all_busy_raises_with_tried_list(self) -> None:
        s1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s1.bind(("127.0.0.1", 49321))
        s1.listen(1)
        s2.bind(("127.0.0.1", 49322))
        s2.listen(1)
        try:
            with pytest.raises(auth.AuthError) as exc:
                auth._find_free_loopback_port([49321, 49322])
            msg = str(exc.value)
            assert "49321" in msg
            assert "49322" in msg
            assert "Free one of them" in msg
            # The error must mention a diagnostic command hint.
            assert "lsof" in msg or "netstat" in msg
        finally:
            s1.close()
            s2.close()


# ========================================================== JWT unverified decode

def _encode_jwt_payload(claims: dict) -> str:
    """Build a JWT-shaped string with the given claims. Signature is garbage."""
    import json

    header_b64 = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode("ascii")
    payload_b64 = (
        base64.urlsafe_b64encode(json.dumps(claims).encode("utf-8"))
        .rstrip(b"=")
        .decode("ascii")
    )
    sig_b64 = base64.urlsafe_b64encode(b"sig").rstrip(b"=").decode("ascii")
    return f"{header_b64}.{payload_b64}.{sig_b64}"


class TestDecodeJwtUnverified:
    def test_round_trip(self) -> None:
        token = _encode_jwt_payload({"sub": "auth0|123", "email": "u@example.com"})
        claims = auth.decode_jwt_unverified(token)
        assert claims["sub"] == "auth0|123"
        assert claims["email"] == "u@example.com"

    def test_malformed_raises(self) -> None:
        with pytest.raises(auth.AuthError):
            auth.decode_jwt_unverified("not-a-jwt")
        with pytest.raises(auth.AuthError):
            auth.decode_jwt_unverified("a.b")  # only two segments

    def test_non_json_payload_raises(self) -> None:
        header = base64.urlsafe_b64encode(b"{}").rstrip(b"=").decode("ascii")
        bad = base64.urlsafe_b64encode(b"\xff\xff\xff").rstrip(b"=").decode("ascii")
        sig = base64.urlsafe_b64encode(b"x").rstrip(b"=").decode("ascii")
        with pytest.raises(auth.AuthError):
            auth.decode_jwt_unverified(f"{header}.{bad}.{sig}")


# =============================================================== expiry helpers

class TestExpiryHelpers:
    def test_round_trip(self) -> None:
        iso = auth._compute_expiry_iso(3600)
        parsed = auth._parse_expiry_iso(iso)
        # Allow a few seconds of slop from wall-clock between the two calls.
        now = datetime.now(timezone.utc)
        delta = (parsed - now).total_seconds()
        assert 3595 <= delta <= 3605

    def test_parse_iso_without_tz_becomes_utc(self) -> None:
        parsed = auth._parse_expiry_iso("2030-01-01T00:00:00")
        assert parsed.tzinfo is not None


# ========================================================= get_access_token env

class TestGetAccessTokenEnvOverride:
    def test_env_var_short_circuits_keyring(self) -> None:
        # Even with an empty keyring, ARIADNE_ACCESS_TOKEN wins.
        store = auth.InMemoryKeyringStore()
        got = auth.get_access_token(
            "https://x.example", store=store, env={"ARIADNE_ACCESS_TOKEN": "env-tk"}
        )
        assert got == "env-tk"

    def test_env_var_beats_cached_token(self) -> None:
        store = auth.InMemoryKeyringStore()
        store.set(
            "https://x.example",
            auth.SLOT_ACCESS_TOKEN,
            "kr-tk",
        )
        store.set(
            "https://x.example",
            auth.SLOT_ACCESS_EXPIRY,
            auth._compute_expiry_iso(3600),
        )
        got = auth.get_access_token(
            "https://x.example", store=store, env={"ARIADNE_ACCESS_TOKEN": "env-tk"}
        )
        assert got == "env-tk"

    def test_cached_token_used_when_not_near_expiry(self) -> None:
        store = auth.InMemoryKeyringStore()
        store.set("https://x.example", auth.SLOT_ACCESS_TOKEN, "kr-tk")
        store.set(
            "https://x.example",
            auth.SLOT_ACCESS_EXPIRY,
            auth._compute_expiry_iso(3600),
        )
        got = auth.get_access_token("https://x.example", store=store, env={})
        assert got == "kr-tk"

    def test_missing_refresh_token_raises(self) -> None:
        # No cached access token, no refresh token, no env var -> AuthError.
        store = auth.InMemoryKeyringStore()
        with pytest.raises(auth.AuthError) as exc:
            auth.get_access_token("https://x.example", store=store, env={})
        assert "ariadne login" in str(exc.value)

    def test_near_expiry_triggers_refresh_path_without_refresh_token_raises(self) -> None:
        """If access is near-expiry but no refresh token, we must fail loud."""
        store = auth.InMemoryKeyringStore()
        store.set("https://x.example", auth.SLOT_ACCESS_TOKEN, "kr-tk")
        # 30s away — inside the 60s threshold.
        near = datetime.now(timezone.utc) + timedelta(seconds=30)
        store.set("https://x.example", auth.SLOT_ACCESS_EXPIRY, near.isoformat())
        with pytest.raises(auth.AuthError):
            auth.get_access_token("https://x.example", store=store, env={})


# =================================================================== whoami

class TestWhoami:
    def test_missing_access_token_raises(self) -> None:
        store = auth.InMemoryKeyringStore()
        with pytest.raises(auth.AuthError):
            auth.whoami("https://x.example", store=store)

    def test_round_trip_with_valid_token(self) -> None:
        store = auth.InMemoryKeyringStore()
        token = _encode_jwt_payload(
            {"sub": "auth0|abc", "email": "d@example.com", "exp": 9999999999}
        )
        store.set("https://x.example", auth.SLOT_ACCESS_TOKEN, token)
        store.set(
            "https://x.example",
            auth.SLOT_ACCESS_EXPIRY,
            auth._compute_expiry_iso(1800),
        )
        info = auth.whoami("https://x.example", store=store)
        assert info["host"] == "https://x.example"
        assert info["user_email"] == "d@example.com"
        assert info["user_sub"] == "auth0|abc"
        assert info["access_expiry"] is not None
        assert isinstance(info["expires_in_seconds"], int)
        assert 1795 <= info["expires_in_seconds"] <= 1800

    def test_undecodable_token_still_returns_host(self) -> None:
        store = auth.InMemoryKeyringStore()
        store.set("https://x.example", auth.SLOT_ACCESS_TOKEN, "garbage")
        info = auth.whoami("https://x.example", store=store)
        assert info["host"] == "https://x.example"
        assert info["user_email"] is None
        assert info["user_sub"] is None


# =========================================================== logout idempotent

def test_logout_idempotent() -> None:
    store = auth.InMemoryKeyringStore()
    # Logout on an empty store must not raise.
    auth.logout("https://x.example", store=store)
    # Seed then logout twice.
    store.set("https://x.example", auth.SLOT_ACCESS_TOKEN, "x")
    store.set("https://x.example", auth.SLOT_REFRESH_TOKEN, "y")
    store.set("https://x.example", auth.SLOT_ACCESS_EXPIRY, "2030-01-01T00:00:00+00:00")
    auth.logout("https://x.example", store=store)
    auth.logout("https://x.example", store=store)
    assert store.get("https://x.example", auth.SLOT_ACCESS_TOKEN) is None
    assert store.get("https://x.example", auth.SLOT_REFRESH_TOKEN) is None
    assert store.get("https://x.example", auth.SLOT_ACCESS_EXPIRY) is None


# ============================================================ relative time UX

class TestFormatRelativeTime:
    def test_seconds(self) -> None:
        assert auth.format_relative_time(1) == "1 second from now"
        assert auth.format_relative_time(45) == "45 seconds from now"
        assert auth.format_relative_time(-45) == "45 seconds ago"

    def test_minutes(self) -> None:
        assert auth.format_relative_time(300) == "5 minutes from now"
        assert auth.format_relative_time(2520) == "42 minutes from now"
        assert auth.format_relative_time(-300) == "5 minutes ago"

    def test_hours(self) -> None:
        # The minutes / hours boundary is at 90 minutes (90*60=5400s), so
        # tests for "in N hours" must use a value >= 5400.
        assert auth.format_relative_time(3 * 3600) == "in 3 hours"
        assert auth.format_relative_time(-3 * 3600) == "3 hours ago"
        # 5400s rounds to 90 minutes (still minute-band), but 5401s
        # crosses into hour-band and rounds to 2 hours.
        assert auth.format_relative_time(2 * 3600) == "in 2 hours"

    def test_days(self) -> None:
        assert auth.format_relative_time(3 * 86400) == "in 3 days"

    def test_boundary_at_90s(self) -> None:
        # 90s and above is "minute" band; 89s and below is "second" band.
        assert auth.format_relative_time(89) == "89 seconds from now"
        assert auth.format_relative_time(90) == "2 minutes from now"


# ============================================================ whoami formatters

class TestFormatWhoamiHuman:
    def test_three_line_shape_and_alignment(self) -> None:
        info = {
            "host": "https://x.example",
            "user_email": "d@example.com",
            "user_sub": "auth0|abc",
            "access_expiry": "2030-01-01T12:34:56+00:00",
            "expires_in_seconds": 3600,
        }
        out = auth.format_whoami_human(info)
        lines = out.splitlines()
        assert len(lines) == 3
        assert lines[0].startswith("Host:    ")
        assert lines[1].startswith("User:    ")
        assert lines[2].startswith("Expires: ")
        # All three labels should end at the same column: 9 chars
        # ("Host:    " / "User:    " / "Expires: " are each 9 chars
        # long before the value).
        assert lines[0][:9] == "Host:    "
        assert lines[1][:9] == "User:    "
        assert lines[2][:9] == "Expires: "

    def test_expired_token_carries_expired_tag(self) -> None:
        info = {
            "host": "https://x.example",
            "user_email": "d@example.com",
            "user_sub": "auth0|abc",
            "access_expiry": "2020-01-01T00:00:00+00:00",
            "expires_in_seconds": -7200,
        }
        out = auth.format_whoami_human(info)
        assert "EXPIRED" in out
        assert "ago" in out

    def test_missing_fields_graceful(self) -> None:
        info = {
            "host": "https://x.example",
            "user_email": None,
            "user_sub": None,
            "access_expiry": None,
            "expires_in_seconds": None,
        }
        out = auth.format_whoami_human(info)
        assert "(unknown)" in out


class TestFormatWhoamiJson:
    def test_shape(self) -> None:
        import json

        info = {
            "host": "https://x.example",
            "user_email": "d@example.com",
            "user_sub": "auth0|abc",
            "access_expiry": "2030-01-01T12:34:56+00:00",
            "expires_in_seconds": 3600,
        }
        out = auth.format_whoami_json(info)
        parsed = json.loads(out)
        assert parsed == {
            "host": "https://x.example",
            "user": "d@example.com",
            "sub": "auth0|abc",
            "expires": "2030-01-01T12:34:56+00:00",
            "expires_in_seconds": 3600,
        }


# ========================================================== discover_config shape

class TestDiscoverConfig:
    def test_unwraps_auth_object(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = {}

        def fake_get(url: str, *, timeout: float = 30.0):
            captured["url"] = url
            return {
                "auth": {
                    "issuer": "https://tenant.auth0.com/",
                    "client_id": "cid-123",
                    "audience": "https://ariadne-core",
                    "scope": "openid profile email offline_access",
                }
            }

        monkeypatch.setattr(auth, "_http_get_json", fake_get)
        config = auth.discover_config("https://host.example")
        assert config == {
            "issuer": "https://tenant.auth0.com/",
            "client_id": "cid-123",
            "audience": "https://ariadne-core",
            "scope": "openid profile email offline_access",
        }
        assert captured["url"] == "https://host.example/.well-known/ariadne-config"

    def test_missing_auth_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(auth, "_http_get_json", lambda url, **_: {})
        with pytest.raises(auth.AuthError):
            auth.discover_config("https://host.example")

    def test_missing_field_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            auth,
            "_http_get_json",
            lambda url, **_: {
                "auth": {"issuer": "https://t/", "client_id": "x", "audience": "y"}
                # scope missing
            },
        )
        with pytest.raises(auth.AuthError) as exc:
            auth.discover_config("https://host.example")
        assert "scope" in str(exc.value)

    def test_host_trailing_slash_normalized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = {}

        def fake_get(url: str, *, timeout: float = 30.0):
            captured["url"] = url
            return {
                "auth": {
                    "issuer": "https://t/",
                    "client_id": "x",
                    "audience": "y",
                    "scope": "openid",
                }
            }

        monkeypatch.setattr(auth, "_http_get_json", fake_get)
        auth.discover_config("https://host.example///")
        assert captured["url"] == "https://host.example/.well-known/ariadne-config"


# =============================================================== _normalize_host
#
# Security regression tests for CATO-security 2026-04-21T21:14:01Z: the host
# URL we resolve determines which IdP the PKCE flow hits, so anything other
# than https:// (or http:// to loopback, for local dev) must be rejected
# before discover_config is called.

class TestNormalizeHostSchemeEnforcement:
    @pytest.mark.parametrize(
        "bad",
        [
            "http://attacker.example",
            "http://example.com",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "ftp://example.com",
            "data:text/plain,hi",
            "example.com",
            "",
            # xft.5.4: long-form IPv6 loopback rejected per design §4.4
            # (strict allow-list — symmetry with rejecting alternate IPv4
            # forms like 127.000.000.001).
            "http://[0:0:0:0:0:0:0:1]:8000",
            # xft.5.4: RFC 6874 zone-id form — out of scope per design
            # §3 row 6 (zone identifiers are not loopback-canonical and
            # stdlib does not validate them).
            "http://[::1%25lo0]:8000",
            # xft.5.4: round-2 r1 consequence — userinfo on a bracketed
            # IPv6 host now rejects (closes the userinfo-bracket channel
            # of CVE-2025-0938; legitimate userinfo on the discovery URL
            # has no functional purpose).
            "http://user@[::1]:8000",
        ],
    )
    def test_rejects_non_https_and_non_loopback_http(self, bad: str) -> None:
        with pytest.raises(auth.AuthError) as exc:
            auth._normalize_host(bad)
        # Message must name the offending input so the operator can see
        # what value was rejected (the whole point of defence-in-depth
        # at this layer is a loud, debuggable failure).
        assert repr(bad) in str(exc.value) or bad in str(exc.value)

    @pytest.mark.parametrize(
        "good,expected",
        [
            ("https://example.com", "https://example.com"),
            ("https://ariadne.example.com/", "https://ariadne.example.com"),
            ("http://localhost:8000", "http://localhost:8000"),
            ("http://127.0.0.1:8000", "http://127.0.0.1:8000"),
            ("http://localhost", "http://localhost"),
            # xft.5.4: RFC 8252 §7.3 IPv6 loopback redirect URI form,
            # accepted alongside 127.0.0.1.
            ("http://[::1]:8000", "http://[::1]:8000"),
            ("http://[::1]", "http://[::1]"),
            # Trailing-slash strip on IPv6 (round-2 r5 completeness).
            ("http://[::1]:8000/", "http://[::1]:8000"),
            ("http://[::1]:8000/some/path", "http://[::1]:8000/some/path"),
            # Case-insensitive scheme parallels existing IPv4 behaviour.
            ("HTTP://[::1]:8000", "HTTP://[::1]:8000"),
        ],
    )
    def test_accepts_https_and_loopback_http(self, good: str, expected: str) -> None:
        assert auth._normalize_host(good) == expected

    @pytest.mark.parametrize(
        "malformed",
        [
            # --- prefix/postfix channel (round-1 vector) ---
            "http://prefix.[::1]/",
            "http://[::1].postfix/",
            "http://[::1]evil.com",
            "http://[::1]evil.com:8000",
            # ``http://[::1]:8000.evil.com`` — on Python 3.11.4 urlparse
            # ACCEPTs this (only ``.port`` access raises, and the
            # predicate never accesses ``.port``); the §4.3 after-]:port
            # digits-only check is what rejects it. On future patched
            # Python versions urlparse may raise ValueError directly,
            # in which case the §4.7 wrap converts to AuthError. Either
            # way, AuthError.
            "http://[::1]:8000.evil.com",
            "http://localhost[::1]:8000",
            # https-branch CVE-shape parallels.
            "https://[::1]evil.com",
            "https://prefix.[::1]/",
            # --- userinfo channel (round-2 r1 additions) ---
            # ``a]b@[::1]:8000`` etc.: hostname parses to ``'::1'`` but
            # netloc carries the polluted userinfo. Round-1 ``rsplit``
            # workaround would have ACCEPTed; round-2 guard requires
            # netloc to start with ``[`` whenever a bracket appears.
            "http://a]b@[::1]:8000",
            "http://]@[::1]:8000",
            "http://a@b@[::1]:8000",
            # Bracket-and-at confusion shape.
            "http://[a@b@[::1]:8000",
            # https-branch userinfo-with-bracket: on 3.11.4 urlparse
            # raises "Invalid IPv6 URL" — caught by the §4.7 wrap.
            "https://a]b@example.com",
        ],
    )
    def test_rejects_cve_2025_0938_bracket_pollution(self, malformed: str) -> None:
        """CVE-2025-0938 regression lock — urlparse on affected Python
        versions accepts malformed netlocs in two channels:

        (a) brackets in non-host position — ``prefix.[::1]``,
            ``[::1]evil.com``, etc. ``parsed.hostname`` returns ``'::1'``
            while ``parsed.netloc`` carries attacker-controlled
            prefix/postfix.

        (b) brackets in userinfo position (round-2 finding) —
            ``a]b@[::1]:8000``, ``]@[::1]:8000``, etc. Same property:
            ``parsed.hostname`` returns ``'::1'`` while ``parsed.netloc``
            preserves the polluted userinfo, and
            ``urllib.request.Request.host`` returns the polluted netloc.

        Both channels re-open the IdP-selection-poisoning hole that
        ``_normalize_host`` exists (xft.5.1) to close. Some inputs in
        this matrix raise ``ValueError`` from ``urlparse`` itself (the
        ``Invalid IPv6 URL`` shape on 3.11.4; possibly more on patched
        Python versions per CPython #105704); the §4.7 ``ValueError``
        wrap converts those uniformly to ``AuthError``, so this test
        asserts ``AuthError`` regardless of which branch (wrap or guard)
        actually fires.
        """
        with pytest.raises(auth.AuthError):
            auth._normalize_host(malformed)


# ====================================== whoami against Auth0-shaped access tokens
#
# Regression lock against the real Railway deployment behavior observed during
# the xft.5.1 Layer 5 smoke (2026-04-22). These tests use synthetic JWT-shaped
# bytes (hand-built with stdlib base64 + json, tampered signature) — no live
# tokens, no PII, no fixture files on disk.

class TestWhoamiSyntheticJwt:
    """Synthetic-JWT regression tests for ``decode_jwt_unverified`` + the
    ``whoami`` display formatter against Auth0-shaped access tokens.

    Contract note — access-token-as-identity source
    ------------------------------------------------
    OAuth 2.1 defines access tokens as opaque resource-authorization bearer
    credentials. They are NOT required to carry identity claims. Auth0's
    JWT-shaped access tokens happen to carry ``sub``, but ``email`` is NOT
    a default claim on the access token — it lives on the ``id_token``.

    Variant 2 below mirrors the real Auth0 Railway-deployment behavior
    observed during the xft.5.1 Layer 5 smoke (2026-04-22), where
    ``whoami`` correctly fell through to the ``(unknown)`` email display
    because the tenant's access tokens do not carry ``email``.

    Variants 3-5 (added in xft.5.5) lock in the id_token-preferred
    display path: when an id_token is present in the keyring, whoami
    uses IT for email/sub while still reading expiry from the
    access_token's ISO timestamp.

    A future maintainer should NOT "fix" the ``(unknown)`` display by
    naively switching every ``decode_jwt_unverified(access_token)``
    call-site to ``id_token`` — only the whoami display formatter
    prefers id_token, because access_token remains the authority for
    (a) the Bearer header value, (b) expiry checks, and (c) identity
    at call-sites where id_token is absent.
    """

    HOST = "https://fixture.example"

    def _seed_store(self, payload: dict) -> auth.InMemoryKeyringStore:
        store = auth.InMemoryKeyringStore()
        token = _encode_jwt_payload(payload)
        store.set(self.HOST, auth.SLOT_ACCESS_TOKEN, token)
        # Non-expired: seed keyring with a future expiry so whoami's
        # expires_in_seconds > 0 branch fires (the expiry display comes
        # from SLOT_ACCESS_EXPIRY, not from the JWT's exp claim).
        store.set(self.HOST, auth.SLOT_ACCESS_EXPIRY, auth._compute_expiry_iso(3600))
        return store

    def test_variant1_email_present_happy_path(self) -> None:
        """Email-present access token: decode surfaces email, whoami
        formatter renders it (not ``(unknown)``), and non-expired branch
        fires."""
        payload = {
            "sub": "test-user|synthetic-fixture",
            "email": "fixture@example.com",
            "aud": "https://test-api.example.com",
            "iss": "https://test-tenant.auth0.com/",
            "iat": 1700000000,
            "exp": 2000000000,  # far-future; we check dict carries it through verbatim
            "scope": "openid profile email offline_access",
        }
        # Decode surfaces sub + email + exp verbatim.
        claims = auth.decode_jwt_unverified(_encode_jwt_payload(payload))
        assert claims["sub"] == "test-user|synthetic-fixture"
        assert claims["email"] == "fixture@example.com"
        assert claims["exp"] == 2000000000

        # whoami lifts email + sub into the info dict.
        store = self._seed_store(payload)
        info = auth.whoami(self.HOST, store=store)
        assert info["user_email"] == "fixture@example.com"
        assert info["user_sub"] == "test-user|synthetic-fixture"
        assert info["expires_in_seconds"] is not None
        assert info["expires_in_seconds"] > 0  # non-expired branch

        # Human formatter renders the email (not the (unknown) sentinel)
        # and does NOT tag EXPIRED.
        rendered = auth.format_whoami_human(info)
        assert "fixture@example.com" in rendered
        assert "(unknown)" not in rendered
        assert "EXPIRED" not in rendered

    def test_variant2_email_absent_graceful_fallback(self) -> None:
        """Email-absent access token: the shape Auth0 actually emits by
        default. Decode returns dict without ``email`` key; whoami
        formatter falls through to ``(unknown)`` without raising; sub is
        still shown so the user knows which identity they're logged in as."""
        payload = {
            "sub": "google-oauth2|000000000000000000001",
            "aud": "https://test-api.example.com",
            "iss": "https://test-tenant.auth0.com/",
            "iat": 1700000000,
            "exp": 2000000000,
            "scope": "openid profile offline_access",
            # NB: no "email" claim — mirrors real Auth0 access-token default
        }
        claims = auth.decode_jwt_unverified(_encode_jwt_payload(payload))
        assert claims["sub"] == "google-oauth2|000000000000000000001"
        assert "email" not in claims

        store = self._seed_store(payload)
        info = auth.whoami(self.HOST, store=store)
        # whoami normalizes missing email to None (per the isinstance-str guard).
        assert info["user_email"] is None
        assert info["user_sub"] == "google-oauth2|000000000000000000001"

        # Human formatter falls through to (unknown) for email but still
        # surfaces the sub so the user can tell which IdP identity this is.
        rendered = auth.format_whoami_human(info)
        assert "(unknown)" in rendered
        assert "google-oauth2|000000000000000000001" in rendered
        assert "EXPIRED" not in rendered

    # ------------------------------------------------------------------ id_token
    # xft.5.5: login now stores the id_token alongside the
    # access/refresh/expiry slots. whoami prefers the id_token for
    # email/sub display, while expiry continues to come from the
    # access_token's ISO expiry stamp.

    def _seed_store_with_id_token(
        self,
        access_payload: dict,
        id_payload: dict,
        *,
        expires_in: int = 3600,
    ) -> auth.InMemoryKeyringStore:
        store = auth.InMemoryKeyringStore()
        store.set(
            self.HOST,
            auth.SLOT_ACCESS_TOKEN,
            _encode_jwt_payload(access_payload),
        )
        store.set(
            self.HOST,
            auth.SLOT_ID_TOKEN,
            _encode_jwt_payload(id_payload),
        )
        store.set(
            self.HOST,
            auth.SLOT_ACCESS_EXPIRY,
            auth._compute_expiry_iso(expires_in),
        )
        return store

    def test_variant3_id_token_preferred_when_access_token_lacks_email(
        self,
    ) -> None:
        """The motivating case: Auth0 access tokens omit ``email`` by
        default, but the id_token carries it. whoami must surface the
        id_token's email rather than falling to ``(unknown)``."""
        access_payload = {
            "sub": "google-oauth2|1234567890",
            "aud": "https://test-api.example.com",
            "iss": "https://test-tenant.auth0.com/",
            "iat": 1700000000,
            "exp": 2000000000,
            "scope": "openid profile email offline_access",
            # NB: no "email" claim on the access token.
        }
        id_payload = {
            "sub": "google-oauth2|1234567890",
            "email": "d@example.com",
            "email_verified": True,
            "iss": "https://test-tenant.auth0.com/",
            "aud": "auth0-client-id",  # id_tokens use client_id as aud
            "iat": 1700000000,
            "exp": 2000000000,
        }
        store = self._seed_store_with_id_token(access_payload, id_payload)
        info = auth.whoami(self.HOST, store=store)
        assert info["user_email"] == "d@example.com"
        assert info["user_sub"] == "google-oauth2|1234567890"

        rendered = auth.format_whoami_human(info)
        assert "d@example.com" in rendered
        # The (unknown) sentinel must NOT be in the rendered email —
        # the whole point of variant 3 is that we fix the xft.5.1 gap.
        assert "User:    (unknown)" not in rendered
        assert "EXPIRED" not in rendered

    def test_variant4_id_token_email_preferred_over_access_token_email(
        self,
    ) -> None:
        """If both tokens carry email (e.g. a tenant configured to add
        email to access tokens), the id_token still wins — mirrors the
        OIDC contract that identity claims are id_token's job.

        If an operator finds this surprising, note: on a correctly
        configured tenant the two emails agree. On a misconfigured
        tenant, the id_token is the canonical identity source."""
        access_payload = {
            "sub": "auth0|abc",
            "email": "stale-access@example.com",
            "aud": "https://api.example.com",
            "iss": "https://t.auth0.com/",
            "iat": 1700000000,
            "exp": 2000000000,
        }
        id_payload = {
            "sub": "auth0|abc",
            "email": "fresh-id@example.com",
            "iss": "https://t.auth0.com/",
            "aud": "auth0-client-id",
            "iat": 1700000000,
            "exp": 2000000000,
        }
        store = self._seed_store_with_id_token(access_payload, id_payload)
        info = auth.whoami(self.HOST, store=store)
        assert info["user_email"] == "fresh-id@example.com"

    def test_variant5_expiry_comes_from_access_token_not_id_token(
        self,
    ) -> None:
        """Non-swap rule: expiry is ALWAYS read from SLOT_ACCESS_EXPIRY,
        never from ``id_token.exp``. We encode a far-future exp on the
        id_token and a near-past exp on the access-token ISO slot;
        whoami must report expired.

        Without this test, a well-meaning maintainer could "optimize"
        whoami to read ``exp`` from the decoded id_token claims (which
        would silently bypass the refresh-threshold logic that relies
        on SLOT_ACCESS_EXPIRY) and the regression wouldn't surface in
        variant 3/4."""
        # Access token with email absent (triggers id_token preference).
        access_payload = {
            "sub": "auth0|abc",
            "aud": "https://api.example.com",
            "iss": "https://t.auth0.com/",
            "iat": 1700000000,
            "exp": 1800000000,
        }
        # id_token claims a far-future exp — if a future maintainer
        # "fixes" whoami to read this, the test catches it.
        id_payload = {
            "sub": "auth0|abc",
            "email": "d@example.com",
            "iss": "https://t.auth0.com/",
            "aud": "auth0-client-id",
            "iat": 1700000000,
            "exp": 9999999999,  # year ~2286; implausibly far future
        }
        # Seed with a NEGATIVE remaining lifetime: expiry 2h in the past.
        store = self._seed_store_with_id_token(
            access_payload, id_payload, expires_in=-7200
        )
        info = auth.whoami(self.HOST, store=store)
        assert info["user_email"] == "d@example.com"
        # Expiry comes from SLOT_ACCESS_EXPIRY, which we seeded as
        # -2h ago. If whoami started reading id_token.exp we'd get a
        # positive, far-future remaining lifetime instead.
        assert info["expires_in_seconds"] is not None
        assert info["expires_in_seconds"] < 0
        rendered = auth.format_whoami_human(info)
        assert "EXPIRED" in rendered
        assert "ago" in rendered

    def test_variant6_malformed_id_token_falls_back_to_access_token(
        self,
    ) -> None:
        """If the stored id_token is corrupt (3 segments but bad JSON),
        whoami should not raise — it falls back to the access_token
        claims and reports what it can."""
        access_payload = {
            "sub": "auth0|fallback",
            "email": "fallback@example.com",
            "aud": "https://api.example.com",
            "iss": "https://t.auth0.com/",
            "iat": 1700000000,
            "exp": 2000000000,
        }
        store = auth.InMemoryKeyringStore()
        store.set(
            self.HOST,
            auth.SLOT_ACCESS_TOKEN,
            _encode_jwt_payload(access_payload),
        )
        # Malformed id_token — 3 segments but middle segment is
        # non-JSON bytes. decode_jwt_unverified raises AuthError; whoami
        # must swallow it and use access-token claims.
        import base64

        header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
        bad_payload = base64.urlsafe_b64encode(b"\xff\xfe\xff").rstrip(b"=").decode()
        sig = base64.urlsafe_b64encode(b"sig").rstrip(b"=").decode()
        store.set(self.HOST, auth.SLOT_ID_TOKEN, f"{header}.{bad_payload}.{sig}")
        store.set(
            self.HOST,
            auth.SLOT_ACCESS_EXPIRY,
            auth._compute_expiry_iso(3600),
        )
        info = auth.whoami(self.HOST, store=store)
        assert info["user_email"] == "fallback@example.com"
        assert info["user_sub"] == "auth0|fallback"


# =================================================== id_token storage: login+logout
#
# Ensure login persists the id_token on success and logout removes it.

def _make_fake_token_response(
    *,
    access_token: str = "access-tk",
    refresh_token: str = "refresh-tk",
    id_token: str | None = "id-tk",
    expires_in: int = 3600,
) -> dict:
    out: dict = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
    }
    if id_token is not None:
        out["id_token"] = id_token
    return out


class TestIdTokenPersistence:
    HOST = "https://fixture.example"

    def _patch_flow(
        self,
        monkeypatch: pytest.MonkeyPatch,
        token_response: dict,
    ) -> None:
        """Stub the three network / browser steps of ``login`` so we can
        drive it hermetically."""
        monkeypatch.setattr(
            auth,
            "discover_config",
            lambda host, **_: {
                "issuer": "https://t.auth0.com/",
                "client_id": "cid-123",
                "audience": "https://api.example.com",
                "scope": "openid profile email offline_access",
            },
        )

        def fake_find_port(_candidates=None):
            return 65432

        monkeypatch.setattr(auth, "_find_free_loopback_port", fake_find_port)

        def fake_callback(port: int, expected_state: str, **_):
            return "auth-code-xyz", expected_state

        monkeypatch.setattr(auth, "_run_loopback_callback", fake_callback)
        monkeypatch.setattr(
            auth,
            "_exchange_authorization_code",
            lambda *a, **kw: token_response,
        )

    def test_login_stores_id_token_slot(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Build an id_token that actually decodes so the email pulled
        # into the return dict is observable.
        id_token_str = _encode_jwt_payload(
            {"sub": "auth0|abc", "email": "d@example.com"}
        )
        self._patch_flow(
            monkeypatch,
            _make_fake_token_response(id_token=id_token_str),
        )
        store = auth.InMemoryKeyringStore()
        result = auth.login(
            self.HOST,
            store=store,
            open_browser=False,
            write_default=False,
        )
        # All four slots populated.
        assert store.get(self.HOST, auth.SLOT_ACCESS_TOKEN) == "access-tk"
        assert store.get(self.HOST, auth.SLOT_REFRESH_TOKEN) == "refresh-tk"
        assert store.get(self.HOST, auth.SLOT_ID_TOKEN) == id_token_str
        assert store.get(self.HOST, auth.SLOT_ACCESS_EXPIRY) is not None
        assert result["email"] == "d@example.com"

    def test_login_skips_id_token_when_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A token response without id_token (misconfigured tenant) must
        not crash login — id_token slot simply stays empty."""
        self._patch_flow(
            monkeypatch,
            _make_fake_token_response(id_token=None),
        )
        store = auth.InMemoryKeyringStore()
        auth.login(
            self.HOST,
            store=store,
            open_browser=False,
            write_default=False,
        )
        assert store.get(self.HOST, auth.SLOT_ACCESS_TOKEN) == "access-tk"
        assert store.get(self.HOST, auth.SLOT_ID_TOKEN) is None

    def test_logout_clears_id_token_slot(self) -> None:
        store = auth.InMemoryKeyringStore()
        for slot in (
            auth.SLOT_ACCESS_TOKEN,
            auth.SLOT_REFRESH_TOKEN,
            auth.SLOT_ACCESS_EXPIRY,
            auth.SLOT_ID_TOKEN,
        ):
            store.set(self.HOST, slot, "seeded")
        auth.logout(self.HOST, store=store)
        for slot in (
            auth.SLOT_ACCESS_TOKEN,
            auth.SLOT_REFRESH_TOKEN,
            auth.SLOT_ACCESS_EXPIRY,
            auth.SLOT_ID_TOKEN,
        ):
            assert store.get(self.HOST, slot) is None
