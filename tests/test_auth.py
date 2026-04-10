"""Tests for API key authentication."""

import pytest

from pipeline.api.auth import APIKey, InMemoryAPIKeyStore, hash_api_key


class TestHashAPIKey:
    def test_deterministic(self):
        assert hash_api_key("test-key") == hash_api_key("test-key")

    def test_different_keys_different_hash(self):
        assert hash_api_key("key-1") != hash_api_key("key-2")

    def test_returns_hex_sha256(self):
        h = hash_api_key("test")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


class TestInMemoryAPIKeyStore:
    def setup_method(self):
        self.store = InMemoryAPIKeyStore()

    def test_create_and_find(self):
        key = self.store.create_key("test-agent", "raw-key-123")
        assert key.name == "test-agent"
        found = self.store.find_by_hash(hash_api_key("raw-key-123"))
        assert found is not None
        assert found.name == "test-agent"

    def test_find_miss(self):
        assert self.store.find_by_hash("nonexistent") is None

    def test_revoke_key(self):
        key = self.store.create_key("agent", "my-key")
        self.store.revoke_key(key.key_hash)
        assert self.store.find_by_hash(key.key_hash) is None

    def test_revoke_nonexistent_is_noop(self):
        self.store.revoke_key("nonexistent")  # should not raise
