"""
Shared Supabase client for the Flask backend.

Reads connection details from the repo-root `.env` file (see `.env.example`
for the variables this expects — SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY).
Import `supabase` from this module anywhere in the backend instead of
creating a new client per-file.

    from app.extensions import supabase

    supabase.table("events").select("*").execute()

The real client is built lazily, on first attribute access (the `.table`
above), not at import time. Importing this module -- directly, or
transitively through anything in app.events, seed.py, etc. -- must never
require SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY to be set, or CI can't
import the app to run unit tests without real Supabase credentials (see
app/config.py, which reuses ROOT_ENV_PATH below, and the health
blueprint, which relies on /health working with zero credentials).

NOTE: the service role key bypasses Row Level Security entirely. That's
expected for backend/server-side use, but never send this key to the
frontend or log it.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import httpx
from dotenv import load_dotenv
from supabase import Client, ClientOptions, create_client

# Repo layout: backend/app/extensions.py -> parent=app/, parent.parent=
# backend/, parent.parent.parent=repo root. app/config.py imports this
# exact constant rather than recomputing the path, so there's one place
# that knows where .env lives.
ROOT_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=ROOT_ENV_PATH)


class _LazySupabaseClient:
    """Transparent stand-in for a real `Client`. Defers both credential
    validation and client construction until the first real attribute
    access (`.table(...)`, `.auth`, etc.), then caches the constructed
    client for the rest of the process. Constructing this object itself
    never touches the network or the environment."""

    _client: Client | None = None
    _lock = threading.Lock()

    def _get_client(self) -> Client:
        if self._client is not None:
            return self._client
        # Flask's dev server is threaded and a page fires several API calls
        # at once, so the first few requests can all arrive here together:
        # build the client once, under a lock.
        with self._lock:
            if self._client is None:
                self._client = self._build_client()
        return self._client

    @staticmethod
    def _build_client() -> Client:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        missing = [
            name
            for name, value in (("SUPABASE_URL", url), ("SUPABASE_SERVICE_ROLE_KEY", key))
            if not value
        ]
        if missing:
            raise RuntimeError(
                f"Missing {', '.join(missing)}. Copy .env.example to .env "
                "at the repo root and fill in your project's real values "
                "from the Supabase dashboard (Project Settings -> API)."
            )
        # One HTTP/1.1 client shared by PostgREST and auth. supabase-py's
        # default is HTTP/2, whose single shared connection fails on
        # Windows when several Flask threads use it at once:
        # "httpx.ReadError: [WinError 10035] A non-blocking socket
        # operation could not be completed immediately" -- seen as the
        # event page's parallel calls 500ing on first load, then working
        # on reload. With HTTP/1.1 each concurrent request gets its own
        # pooled connection. Timeout matches supabase-py's PostgREST
        # default (120 s); follow_redirects matches its own client.
        http_client = httpx.Client(http2=False, timeout=120.0, follow_redirects=True)
        return create_client(url, key, options=ClientOptions(httpx_client=http_client))

    def __getattr__(self, name: str):
        return getattr(self._get_client(), name)


supabase = _LazySupabaseClient()
