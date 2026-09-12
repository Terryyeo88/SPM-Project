"""
App configuration.

create_app() reads settings from the `Config` class below by default, or
can be handed a config_override (another class or instance with the same
attribute names) so tests build an app without touching a real `.env`.

SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are intentionally NOT validated
here. That validation happens lazily in app.extensions, at first real
Supabase use -- see that module's docstring for why. Config's job is just
to expose whatever is in the environment (or nothing), not to decide
whether it's usable yet.
"""

from __future__ import annotations

import os

# Reuse app.extensions' .env path resolution instead of recomputing it --
# importing app.extensions also runs its module-level load_dotenv(), so by
# the time this module reads os.environ below, the repo-root .env (if any)
# has already been loaded.
from app.extensions import ROOT_ENV_PATH  # noqa: F401 -- re-exported for callers that want the path


class Config:
    SUPABASE_URL: str | None = os.environ.get("SUPABASE_URL")
    SUPABASE_SERVICE_ROLE_KEY: str | None = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    SUPABASE_JWT_SECRET: str | None = os.environ.get("SUPABASE_JWT_SECRET")
    # `or` (not the dict-style default) because os.environ.get's default
    # only applies when the key is absent -- present-but-empty must also
    # fall back to 30, or int("") raises.
    SESSION_IDLE_TIMEOUT_MINUTES: int = int(os.environ.get("SESSION_IDLE_TIMEOUT_MINUTES") or "30")
    TESTING: bool = False
