"""
The rule deciding where integration tests may run (tests/conftest.py):
local Supabase always, a non-local one only with an explicit, exact opt-in,
nothing without credentials. Pure functions of a URL / an environ dict --
no database, no network.
"""

from __future__ import annotations

import pytest
from conftest import REMOTE_OPT_IN_VALUE, REMOTE_OPT_IN_VAR, integration_skip_reason, is_local_supabase

LIVE = "https://abcdefghijklmnop.supabase.co"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:54321",  # CLI default
        "http://127.0.0.1:55321",  # CLI with shifted ports
        "http://localhost:54321",
        "http://LOCALHOST:54321",
        "http://127.8.9.10:54321",  # all of 127.0.0.0/8 is loopback
        "http://[::1]:54321",
    ],
)
def test_local_supabase_urls_are_local(url):
    assert is_local_supabase(url)


@pytest.mark.parametrize(
    "url",
    [
        LIVE,
        "https://db.YOUR_PROJECT_REF.supabase.co",
        "http://localhost.example.com:54321",  # lookalike host
        "http://127.0.0.1.nip.io:54321",  # resolves to loopback, but we don't resolve -- fail safe
        "http://192.168.1.20:54321",  # a LAN machine is not this machine
        "http://0.0.0.0:54321",
        "http://[YOUR-PROJECT]:5432",  # unparseable placeholder
        "not a url",
        "",
    ],
)
def test_everything_else_is_not_local(url):
    assert not is_local_supabase(url)


def test_local_runs_with_no_opt_in():
    assert integration_skip_reason({"SUPABASE_URL": "http://127.0.0.1:54321", "SUPABASE_SERVICE_ROLE_KEY": "k"}) is None


@pytest.mark.parametrize("env", [{}, {"SUPABASE_URL": LIVE}, {"SUPABASE_SERVICE_ROLE_KEY": "k"}])
def test_missing_credentials_skip_with_a_how_to(env):
    reason = integration_skip_reason(env)
    assert reason.startswith("no SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY set")
    assert "npx supabase start" in reason


def test_remote_is_refused_by_default_with_instructions():
    reason = integration_skip_reason({"SUPABASE_URL": LIVE, "SUPABASE_SERVICE_ROLE_KEY": "k"})
    assert "abcdefghijklmnop.supabase.co" in reason
    assert "not a local Supabase" in reason
    assert "npx supabase start" in reason
    assert f"{REMOTE_OPT_IN_VAR}={REMOTE_OPT_IN_VALUE}" in reason


@pytest.mark.parametrize("value", ["1", "true", "yes", "YES-WRITE-TEST-DATA-TO-THE-SHARED-PROJECT", ""])
def test_remote_opt_in_requires_the_exact_value(value):
    reason = integration_skip_reason({"SUPABASE_URL": LIVE, "SUPABASE_SERVICE_ROLE_KEY": "k", REMOTE_OPT_IN_VAR: value})
    assert reason is not None
    if value:
        assert "not to the exact required value" in reason


def test_remote_runs_with_the_exact_opt_in():
    env = {"SUPABASE_URL": LIVE, "SUPABASE_SERVICE_ROLE_KEY": "k", REMOTE_OPT_IN_VAR: REMOTE_OPT_IN_VALUE}
    assert integration_skip_reason(env) is None


def test_secret_key_never_appears_in_a_skip_reason():
    reason = integration_skip_reason({"SUPABASE_URL": LIVE, "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_DO_NOT_PRINT"})
    assert "sb_secret_DO_NOT_PRINT" not in reason
