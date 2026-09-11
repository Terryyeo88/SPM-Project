"""
Shared Supabase client for the Flask backend.

Reads connection details from the repo-root `.env` file (see `.env.example`
for the variables this expects — SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY).
Import `supabase` from this module anywhere in the backend instead of
creating a new client per-file.

    from supabase_client import supabase

    supabase.table("events").select("*").execute()

NOTE: the service role key bypasses Row Level Security entirely. That's
expected for backend/server-side use, but never send this key to the
frontend or log it.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client, Client

# Always resolve the repo-root .env, regardless of the current working
# directory the Flask app happens to be started from.
_ROOT_ENV = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_ROOT_ENV)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError(
        "Missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY. "
        "Copy .env.example to .env at the repo root and fill in your "
        "project's real values from the Supabase dashboard "
        "(Project Settings -> API)."
    )

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
