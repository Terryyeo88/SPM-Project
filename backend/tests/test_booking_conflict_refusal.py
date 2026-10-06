"""Unit tests: a confirm refused by IS-16's exclusion constraint becomes
the same ValidationError the app-level overlap check already raises,
instead of a raw database error (a 500).

No database: booking_service's supabase client is replaced with a stub
whose write raises the APIError PostgREST would.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

import app.venues.booking_service as service_module
from app.shared.errors import ValidationError


class _RefusingTable:
    """Every builder call chains; execute() raises `error`."""

    def __init__(self, error: APIError):
        self.error = error

    def __getattr__(self, name):
        return lambda *args, **kwargs: self

    def execute(self):
        raise self.error


def _refused_with(monkeypatch, code: str) -> list:
    error = APIError({"message": "refused", "code": code, "hint": None, "details": None})
    monkeypatch.setattr(service_module, "supabase", SimpleNamespace(table=lambda name: _RefusingTable(error)))
    logged = []
    monkeypatch.setattr(service_module, "_record_booking_status_change", lambda *a, **k: logged.append(a))
    return logged


_PENDING = SimpleNamespace(status="pending")


@pytest.mark.parametrize("code", ["23P01", "40P01"])
def test_constraint_refusal_reads_like_the_app_check(monkeypatch, code):
    logged = _refused_with(monkeypatch, code)

    with pytest.raises(ValidationError) as refused:
        service_module._decide_booking("booking-1", _PENDING, "confirmed", "staff-1", None)

    assert "already has a confirmed booking overlapping this period" in refused.value.message
    assert logged == []  # no history row for a decision that didn't happen


def test_other_database_errors_are_not_disguised_as_overlaps(monkeypatch):
    _refused_with(monkeypatch, "23503")  # foreign key violation

    with pytest.raises(APIError):
        service_module._decide_booking("booking-1", _PENDING, "confirmed", "staff-1", None)
