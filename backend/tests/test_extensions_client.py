"""
How app.extensions builds the shared Supabase client.

Regression cover for the event page's parallel calls failing on first load
on Windows ("httpx.ReadError: [WinError 10035] A non-blocking socket
operation could not be completed immediately"): supabase-py's default
HTTP/2 client shares one connection between Flask's threads. The backend
now hands supabase-py an HTTP/1.1 httpx client, and builds the shared
client once even when several requests arrive together.

No network: create_client is replaced, so nothing here connects anywhere.
"""

from __future__ import annotations

import threading
import time

import httpx

import app.extensions as extensions
from app.extensions import _LazySupabaseClient

# Captured at import, before conftest's autouse guard swaps _get_client for
# one that refuses (that guard is what keeps every OTHER unit test offline).
_REAL_GET_CLIENT = _LazySupabaseClient._get_client


def test_client_is_built_with_an_http1_httpx_client(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    captured = {}

    def fake_create_client(url, key, options=None):
        captured.update(url=url, key=key, options=options)
        return "client"

    monkeypatch.setattr(extensions, "create_client", fake_create_client)

    assert _LazySupabaseClient._build_client() == "client"
    http_client = captured["options"].httpx_client
    assert isinstance(http_client, httpx.Client)
    # httpx keeps the flag on its connection pool; private, but it is the
    # one thing this test exists to pin.
    assert http_client._transport._pool._http2 is False
    assert http_client.follow_redirects is True
    http_client.close()


def test_concurrent_first_requests_build_the_client_once(monkeypatch):
    builds = []

    def slow_build():
        builds.append(1)
        time.sleep(0.05)  # widen the window two threads could both build in
        return object()

    monkeypatch.setattr(_LazySupabaseClient, "_build_client", staticmethod(slow_build))
    lazy = _LazySupabaseClient()
    results = []
    threads = [threading.Thread(target=lambda: results.append(_REAL_GET_CLIENT(lazy))) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(builds) == 1
    assert len({id(r) for r in results}) == 1
