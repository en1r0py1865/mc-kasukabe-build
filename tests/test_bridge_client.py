"""Tests for BridgeClient — focus on schem_list() filesystem canary."""
from __future__ import annotations

import pytest
import requests as _requests

from kasukabe.bridge_client import BridgeClient


class TestSchemListViaHttp:
    """BridgeClient.schem_list must drive GET /fawe_schem_list (filesystem).

    Regression: two previous implementations failed:
      1. Original: POST to bridge /command (bot.chat, fire-and-forget) —
         response never captured, returned [].
      2. Second attempt: RCON `//schem list` — FAWE/WorldEdit routes
         output to the player chat packet, not to RCON's reply stream,
         so RCON always returned empty.
    The SKILL.md Step 5.5 canary depends on this returning the real
    schem list; it must go through the bridge's filesystem endpoint.
    """

    def test_returns_names_from_bridge(self, monkeypatch):
        class FakeResp:
            def raise_for_status(self): pass
            def json(self): return {"names": ["build", "demo_cabin"], "schem_dir": "/x"}
        monkeypatch.setattr(
            "kasukabe.bridge_client.requests.get",
            lambda *a, **k: FakeResp(),
        )
        assert "build" in BridgeClient().schem_list()

    def test_empty_when_dir_missing(self, monkeypatch):
        class FakeResp:
            def raise_for_status(self): pass
            def json(self): return {"names": [], "schem_dir": None}
        monkeypatch.setattr(
            "kasukabe.bridge_client.requests.get",
            lambda *a, **k: FakeResp(),
        )
        assert BridgeClient().schem_list() == []

    def test_does_not_call_rcon(self, monkeypatch):
        """Regression: FAWE output is invisible to RCON; schem_list must
        never reach for rcon_client.from_env anymore."""
        class FakeResp:
            def raise_for_status(self): pass
            def json(self): return {"names": []}
        monkeypatch.setattr(
            "kasukabe.bridge_client.requests.get",
            lambda *a, **k: FakeResp(),
        )
        import kasukabe.rcon_client as rc
        def _explode():
            raise AssertionError("schem_list must not open RCON")
        monkeypatch.setattr(rc, "from_env", lambda: _explode())
        BridgeClient().schem_list()

    def test_propagates_http_error(self, monkeypatch):
        class FakeResp:
            def raise_for_status(self):
                raise _requests.HTTPError("500")
            def json(self): return {}
        monkeypatch.setattr(
            "kasukabe.bridge_client.requests.get",
            lambda *a, **k: FakeResp(),
        )
        with pytest.raises(_requests.HTTPError):
            BridgeClient().schem_list()

    def test_calls_correct_endpoint(self, monkeypatch):
        seen = {}
        class FakeResp:
            def raise_for_status(self): pass
            def json(self): return {"names": []}
        def fake_get(url, **k):
            seen["url"] = url
            return FakeResp()
        monkeypatch.setattr("kasukabe.bridge_client.requests.get", fake_get)
        BridgeClient().schem_list()
        assert seen["url"].endswith("/fawe_schem_list")

    def test_raises_on_missing_names_key(self, monkeypatch):
        """If bridge predates /fawe_schem_list (returns an unrelated
        JSON body), we must fail loudly rather than silently return []
        — a silent empty list looks identical to 'build.schem not
        uploaded', which sends the agent down the wrong diagnostic path.
        """
        class FakeResp:
            def raise_for_status(self): pass
            def json(self): return {"error": "not found"}
        monkeypatch.setattr(
            "kasukabe.bridge_client.requests.get",
            lambda *a, **k: FakeResp(),
        )
        with pytest.raises(RuntimeError, match="no 'names' field"):
            BridgeClient().schem_list()
