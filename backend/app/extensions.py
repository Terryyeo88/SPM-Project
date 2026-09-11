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
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client, Client

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

    def _get_client(self) -> Client:
        if self._client is None:
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
            self._client = create_client(url, key)
        return self._client

    def __getattr__(self, name: str):
        return getattr(self._get_client(), name)


supabase = _LazySupabaseClient()
