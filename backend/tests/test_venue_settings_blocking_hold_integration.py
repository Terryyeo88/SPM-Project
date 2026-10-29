"""Live Supabase integration tests for Sprint 3's venue-settings editing,
venue blocking, and tentative-hold release mechanism (Josiah) -- only
what a unit test structurally cannot prove:

1. The 'released' enum value round-trips for real (the isolated-migration
   requirement for ALTER TYPE ... ADD VALUE actually holds on db reset).
2. update_venue (IS-61's edit path, which tentative_hold_minutes editing
   was folded into after merging with main -- see
   docs/design-decisions.md) never retroactively changes an existing
   booking (the snapshot-immutability invariant venue_service.py's own
   docstring states as a proof, not an assumption).
3. The confirm-time guard against venue_blocks works against a real
   venue_blocks row (not just a fake).
4. release_bookings_for_event (cancel) actually writes 'released' and the
   audit log, against real tables.
5. The exclusion-constraint-frees-on-release interaction end to end:
   confirming a booking whose hold has expired must release it, which
   must free the GiST constraint for a different, overlapping booking to
   confirm -- the same IS-16 constraint test_booking_conflicts_integration.py
   proves for `rejected`, now proven for `released` too.
6. has_live_confirmed_booking (confirm_event's gate) correctly reports
   false once a booking's hold has expired.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

from app.extensions import supabase
from app.shared.errors import NotFoundError, ValidationError
from app.venues.block_service import create_venue_block
from app.venues.booking_release import release_bookings_for_event
from app.venues.booking_service import confirm_booking, has_live_confirmed_booking
from app.venues.venue_service import update_venue
from tests.conftest import is_local_supabase

pytestmark = pytest.mark.integration

_SGT_OFFSET = timedelta(hours=8)


class _Fixtures:
    def __init__(self):
        self.booking_ids: list[str] = []
        self.event_ids: list[str] = []
        self.venue_ids: list[str] = []
        self.user_ids: list[str] = []
        self.block_ids: list[str] = []
        self.requester = self._create_user("event_coordinator")

    def _create_user(self, role: str) -> str:
        email = f"venue-settings-test-{uuid.uuid4()}@example.com"
        created = supabase.auth.admin.create_user(
            {"email": email, "password": "Password123!-throwaway-test-account", "email_confirm": True}
        )
        user_id = created.user.id
        self.user_ids.append(user_id)
        supabase.table("profiles").insert({"id": user_id, "name": "Venue Settings Test", "email": email}).execute()
        supabase.table("user_roles").insert({"user_id": user_id, "role": role}).execute()
        return user_id

    def create_venue(self, **overrides) -> dict:
        payload = {
            "name": f"Venue Settings Test Venue {uuid.uuid4()}",
            "location": "Test Wing",
            "capacity": 100,
            "facilities": [],
            "accessibility_features": [],
            "supported_layouts": ["theatre"],
            "status": "available",
            "setup_minutes": 30,
            "turnaround_minutes": 30,
            "tentative_hold_minutes": 60,
        }
        payload.update(overrides)
        venue = supabase.table("venues").insert(payload).execute().data[0]
        self.venue_ids.append(venue["id"])
        return venue

    def create_event(self, **overrides) -> dict:
        payload = {
            "name": f"Venue Settings Test Event {uuid.uuid4()}",
            "description": "safe to delete",
            "organizer_id": self.requester,
            "coordinator_id": self.requester,
            "status": "planning",
        }
        payload.update(overrides)
        event = supabase.table("events").insert(payload).execute().data[0]
        self.event_ids.append(event["id"])
        return event

    def create_booking(self, event_id: str, venue_id: str, status: str = "pending", **overrides) -> dict:
        payload = {
            "event_id": event_id,
            "venue_id": venue_id,
            "status": status,
            "requested_by": self.requester,
            "setup_minutes": 0,
            "turnaround_minutes": 0,
            "booking_start": overrides.pop("booking_start", "2026-12-01T08:00:00+08:00"),
            "booking_end": overrides.pop("booking_end", "2026-12-01T10:00:00+08:00"),
        }
        payload.update(overrides)
        booking = supabase.table("venue_bookings").insert(payload).execute().data[0]
        self.booking_ids.append(booking["id"])
        return booking

    def cleanup(self) -> None:
        for block_id in self.block_ids:
            supabase.table("venue_blocks").delete().eq("id", block_id).execute()
        for booking_id in self.booking_ids:
            supabase.table("venue_bookings").delete().eq("id", booking_id).execute()
        for event_id in self.event_ids:
            supabase.table("events").delete().eq("id", event_id).execute()
        for venue_id in self.venue_ids:
            supabase.table("venues").delete().eq("id", venue_id).execute()
        for user_id in self.user_ids:
            supabase.table("user_roles").delete().eq("user_id", user_id).execute()
            supabase.table("profiles").delete().eq("id", user_id).execute()
            supabase.auth.admin.delete_user(user_id)


@pytest.fixture
def fixtures():
    if not is_local_supabase(os.environ.get("SUPABASE_URL", "")):
        pytest.skip("Sprint 3 venue settings/blocking tests write real rows -- local Supabase only.")
    f = _Fixtures()
    try:
        yield f
    finally:
        f.cleanup()


# -- 1. 'released' round-trips for real -------------------------------------


def test_released_status_round_trips(fixtures):
    venue = fixtures.create_venue()
    event = fixtures.create_event()
    booking = fixtures.create_booking(event["id"], venue["id"], status="confirmed")

    released = release_bookings_for_event(event["id"], "Event cancelled", changed_by=fixtures.requester)

    assert [b["id"] for b in released] == [booking["id"]]
    refetched = supabase.table("venue_bookings").select("status").eq("id", booking["id"]).execute().data[0]
    assert refetched["status"] == "released"
    log_rows = (
        supabase.table("venue_booking_status_log").select("*").eq("booking_id", booking["id"]).execute().data
    )
    assert any(row["to_status"] == "released" and row["reason"] == "Event cancelled" for row in log_rows)


# -- 2. editing venue settings never changes an existing booking -------------


def test_editing_venue_settings_does_not_change_existing_booking(fixtures):
    venue = fixtures.create_venue(setup_minutes=30, turnaround_minutes=30, tentative_hold_minutes=60)
    event = fixtures.create_event()
    booking = fixtures.create_booking(event["id"], venue["id"], setup_minutes=30, turnaround_minutes=30)

    update_venue(venue["id"], {"setup_minutes": 999, "turnaround_minutes": 999, "tentative_hold_minutes": 999})

    refetched = supabase.table("venue_bookings").select("*").eq("id", booking["id"]).execute().data[0]
    assert refetched["setup_minutes"] == 30
    assert refetched["turnaround_minutes"] == 30


def test_update_venue_settings_rejects_a_non_positive_value_for_real(fixtures):
    venue = fixtures.create_venue()
    with pytest.raises(ValidationError):
        update_venue(venue["id"], {"setup_minutes": 0})


# -- 3. confirm-time guard against a real venue_blocks row -------------------


def test_confirm_booking_refused_against_a_real_venue_block(fixtures):
    venue = fixtures.create_venue()
    event = fixtures.create_event()
    booking = fixtures.create_booking(
        event["id"], venue["id"], status="pending",
        booking_start="2026-12-05T08:00:00+08:00", booking_end="2026-12-05T10:00:00+08:00",
    )
    create_venue_block(
        venue["id"],
        {
            "reason": "maintenance",
            "block_start": "2026-12-05T00:00:00+08:00",
            "block_end": "2026-12-06T00:00:00+08:00",
        },
        fixtures.requester,
    )

    with pytest.raises(ValidationError):
        confirm_booking(booking["id"], SimpleNamespace(**booking), fixtures.requester)

    refetched = supabase.table("venue_bookings").select("status").eq("id", booking["id"]).execute().data[0]
    assert refetched["status"] == "pending"


def test_create_venue_block_releases_a_real_overlapping_confirmed_booking(fixtures):
    venue = fixtures.create_venue()
    event = fixtures.create_event()
    booking = fixtures.create_booking(
        event["id"], venue["id"], status="confirmed",
        booking_start="2026-12-07T08:00:00+08:00", booking_end="2026-12-07T10:00:00+08:00",
    )

    result = create_venue_block(
        venue["id"],
        {
            "reason": "safety_issue",
            "block_start": "2026-12-07T00:00:00+08:00",
            "block_end": "2026-12-08T00:00:00+08:00",
        },
        fixtures.requester,
    )
    fixtures.block_ids.append(result["block"]["id"])

    assert result["released_bookings"] == [{"booking_id": booking["id"], "event_id": event["id"]}]
    refetched = supabase.table("venue_bookings").select("status").eq("id", booking["id"]).execute().data[0]
    assert refetched["status"] == "released"


def test_create_venue_block_raises_not_found_for_an_unknown_venue(fixtures):
    body = {"reason": "other", "block_start": "2026-12-01T00:00:00+08:00", "block_end": "2026-12-02T00:00:00+08:00"}
    with pytest.raises(NotFoundError):
        create_venue_block(str(uuid.uuid4()), body, fixtures.requester)


# -- 4. has_live_confirmed_booking reports false once a hold expires ---------


def test_has_live_confirmed_booking_is_false_once_the_hold_expires(fixtures):
    venue = fixtures.create_venue()
    event = fixtures.create_event(status="safety_review")
    expired_confirmed_at = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    booking = fixtures.create_booking(
        event["id"], venue["id"], status="confirmed", confirmed_at=expired_confirmed_at, hold_minutes=60
    )

    assert has_live_confirmed_booking(event["id"]) is False

    refetched = supabase.table("venue_bookings").select("status").eq("id", booking["id"]).execute().data[0]
    assert refetched["status"] == "released"


def test_has_live_confirmed_booking_is_true_within_the_hold_window(fixtures):
    venue = fixtures.create_venue()
    event = fixtures.create_event(status="safety_review")
    recent_confirmed_at = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    fixtures.create_booking(
        event["id"], venue["id"], status="confirmed", confirmed_at=recent_confirmed_at, hold_minutes=60
    )

    assert has_live_confirmed_booking(event["id"]) is True


def test_has_live_confirmed_booking_is_true_for_an_already_confirmed_event_however_old(fixtures):
    """The graduated-event guard, proven against real Postgres: once the
    EVENT itself is confirmed, elapsed hold time is meaningless."""
    venue = fixtures.create_venue()
    event = fixtures.create_event(status="confirmed")
    ancient_confirmed_at = "2020-01-01T00:00:00+00:00"
    fixtures.create_booking(
        event["id"], venue["id"], status="confirmed", confirmed_at=ancient_confirmed_at, hold_minutes=60
    )

    assert has_live_confirmed_booking(event["id"]) is True


# -- 5. exclusion constraint frees for 'released' too, against real Postgres -


def test_releasing_an_expired_hold_frees_the_exclusion_constraint_for_another_booking(fixtures):
    """Same proof test_booking_conflicts_integration.py already has for
    `rejected` (IS-16), now for `released`: only confirmed rows are in
    the constraint's scope, so a booking that leaves confirmed via
    release frees its period at once, with no extra handling."""
    venue = fixtures.create_venue()
    event_a = fixtures.create_event(status="safety_review")
    event_b = fixtures.create_event(status="planning")
    expired_confirmed_at = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    fixtures.create_booking(
        event_a["id"], venue["id"], status="confirmed",
        booking_start="2026-12-09T08:00:00+08:00", booking_end="2026-12-09T10:00:00+08:00",
        confirmed_at=expired_confirmed_at, hold_minutes=60,
    )
    booking_b = fixtures.create_booking(
        event_b["id"], venue["id"], status="pending",
        booking_start="2026-12-09T09:00:00+08:00", booking_end="2026-12-09T11:00:00+08:00",
    )

    # Confirming B would clash with A's still-"confirmed" DB row -- unless
    # touching A (via has_live_confirmed_booking, same as the confirm_event
    # gate would) releases it first.
    with pytest.raises(APIError) as refused:
        supabase.table("venue_bookings").update({"status": "confirmed"}).eq("id", booking_b["id"]).execute()
    assert refused.value.code == "23P01"

    assert has_live_confirmed_booking(event_a["id"]) is False  # touches and releases A

    supabase.table("venue_bookings").update({"status": "confirmed"}).eq("id", booking_b["id"]).execute()
    refetched_b = supabase.table("venue_bookings").select("status").eq("id", booking_b["id"]).execute().data[0]
    assert refetched_b["status"] == "confirmed"
