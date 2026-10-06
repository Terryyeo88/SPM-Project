"""Live Supabase integration tests for IS-16 -- only what a unit test
structurally cannot prove:

1. The exclusion constraint really refuses a concurrent double booking,
   shown with a NEGATIVE CONTROL: with the constraint dropped, two
   concurrent confirms of overlapping bookings both land; with it
   restored, exactly one does.
2. The reporting query and the constraint agree on what "overlap" means
   at the boundaries (touching periods are fine, one minute over is not).

THE NON-OBVIOUS PART: the race is at CONFIRM, not at request. A pending
booking blocks nothing, so inserting two overlapping pending bookings is
legitimate and nothing refuses it. The double booking happens when Venue
Staff confirm both: confirm_booking checks for a confirmed overlap, then
_decide_booking writes in a separate statement, so two confirms can both
pass the check before either writes. The constraint still closes this
because Postgres evaluates an exclusion constraint on UPDATE as well as on
INSERT: the pending -> confirmed UPDATE adds the row to the constraint's
scope (WHERE status = 'confirmed'), and that is when it is checked.

The race fires the WRITE half (the same conditional UPDATE _decide_booking
runs) from two threads at once. Racing the full confirm_booking would only
sometimes interleave so that both checks pass before either write, and a
negative control that only sometimes shows the bug proves nothing. Firing
the writes directly IS the "both checks already passed" interleaving.

The constraint is dropped and restored with `npx supabase db query`, which
only ever talks to the LOCAL stack. This test also skips unless
SUPABASE_URL is local, even when the shared-project opt-in is set:
dropping a constraint on the database the team demos from must not be
possible from a test run.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from postgrest.exceptions import APIError

from app.extensions import supabase
from app.venues.booking_conflicts import confirmed_clashes
from tests.conftest import is_local_supabase

pytestmark = pytest.mark.integration

_PASSWORD = "Password123!-throwaway-test-account"
_CONSTRAINT = "venue_bookings_no_confirmed_overlap"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SGT = timezone(timedelta(hours=8))


def _sql(statement: str) -> list[dict]:
    """Run SQL against the LOCAL stack only (DDL isn't possible through PostgREST)."""
    npx = shutil.which("npx")
    if npx is None:
        pytest.skip("npx not found; the negative control needs the Supabase CLI.")
    completed = subprocess.run(
        [npx, "supabase", "db", "query", statement],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    out = completed.stdout
    if "{" not in out:
        return []  # DDL prints only a command tag, e.g. "ALTER TABLE"
    return json.loads(out[out.index("{") :]).get("rows", [])


def _constraint_definition() -> str | None:
    rows = _sql(f"select pg_get_constraintdef(oid) as def from pg_constraint where conname = '{_CONSTRAINT}'")
    return rows[0]["def"] if rows else None


class _Fixtures:
    def __init__(self):
        self.booking_ids: list[str] = []
        self.event_ids: list[str] = []
        self.venue_ids: list[str] = []
        self.user_ids: list[str] = []
        self.requester = self._create_user()
        self.venue_id = self._create_venue()

    def _create_user(self) -> str:
        email = f"conflict-test-{uuid.uuid4()}@example.com"
        created = supabase.auth.admin.create_user({"email": email, "password": _PASSWORD, "email_confirm": True})
        user_id = created.user.id
        self.user_ids.append(user_id)
        supabase.table("profiles").insert({"id": user_id, "name": "Conflict Test", "email": email}).execute()
        supabase.table("user_roles").insert({"user_id": user_id, "role": "event_coordinator"}).execute()
        return user_id

    def _create_venue(self) -> str:
        venue = (
            supabase.table("venues")
            .insert(
                {
                    "name": f"Conflict Test Venue {uuid.uuid4()}",
                    "location": "Test Wing",
                    "capacity": 100,
                    "facilities": [],
                    "accessibility_features": [],
                    "supported_layouts": ["theatre"],
                    "status": "available",
                }
            )
            .execute()
            .data[0]
        )
        self.venue_ids.append(venue["id"])
        return venue["id"]

    def pending_booking(self, start: datetime, end: datetime) -> str:
        """A pending booking holding [start, end) of the test venue."""
        event = (
            supabase.table("events")
            .insert(
                {
                    "name": f"Conflict Test Event {uuid.uuid4()}",
                    "description": "safe to delete",
                    "organizer_id": self.requester,
                }
            )
            .execute()
            .data[0]
        )
        self.event_ids.append(event["id"])
        booking = (
            supabase.table("venue_bookings")
            .insert(
                {
                    "event_id": event["id"],
                    "venue_id": self.venue_id,
                    "status": "pending",
                    "requested_by": self.requester,
                    "setup_minutes": 0,
                    "turnaround_minutes": 0,
                    "booking_start": start.isoformat(),
                    "booking_end": end.isoformat(),
                }
            )
            .execute()
            .data[0]
        )
        self.booking_ids.append(booking["id"])
        return booking["id"]

    def demote_all(self) -> None:
        """Back to pending, so restoring the constraint can't trip over the
        control's deliberate double booking."""
        if self.booking_ids:
            supabase.table("venue_bookings").update({"status": "pending"}).in_("id", self.booking_ids).execute()

    def cleanup(self) -> None:
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
        pytest.skip("IS-16 conflict tests drop and restore a constraint, so they only run against a local Supabase.")
    # Every test here means nothing without the constraint, including after
    # a negative control whose restore failed.
    assert _constraint_definition() is not None, f"{_CONSTRAINT} is missing -- run `npx supabase db reset`."
    f = _Fixtures()
    try:
        yield f
    finally:
        f.cleanup()


def _confirm_concurrently(booking_ids: list[str]) -> list:
    """Fire _decide_booking's conditional UPDATE (pending -> confirmed) for
    every booking at the same instant, one thread each. Returns per-booking
    outcomes: the updated row, or the exception raised."""
    barrier = threading.Barrier(len(booking_ids))
    outcomes: list = [None] * len(booking_ids)

    def run(i, booking_id):
        barrier.wait()
        try:
            result = (
                supabase.table("venue_bookings")
                .update({"status": "confirmed"})
                .eq("id", booking_id)
                .eq("status", "pending")
                .execute()
            )
            outcomes[i] = result.data[0]
        except Exception as exc:  # noqa: BLE001 -- asserted on below
            outcomes[i] = exc

    threads = [threading.Thread(target=run, args=(i, b)) for i, b in enumerate(booking_ids)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return outcomes


def _confirmed_ids(f: _Fixtures) -> set[str]:
    rows = (
        supabase.table("venue_bookings")
        .select("id")
        .in_("id", f.booking_ids)
        .eq("status", "confirmed")
        .execute()
        .data
    )
    return {row["id"] for row in rows}


def test_constraint_refuses_concurrent_confirms_of_overlapping_bookings(fixtures):
    f = fixtures
    definition = _constraint_definition()

    day = datetime(2026, 11, 2, tzinfo=_SGT)
    # 10:00-12:00 and 11:00-13:00 overlap by an hour. Both pending: legal.
    first = f.pending_booking(day.replace(hour=10), day.replace(hour=12))
    second = f.pending_booking(day.replace(hour=11), day.replace(hour=13))

    # NEGATIVE CONTROL: without the constraint, both confirms land -- the
    # double booking the app check alone cannot stop.
    _sql(f"alter table public.venue_bookings drop constraint {_CONSTRAINT}")
    try:
        outcomes = _confirm_concurrently([first, second])
        assert all(isinstance(o, dict) for o in outcomes), outcomes
        assert _confirmed_ids(f) == {first, second}
    finally:
        f.demote_all()
        _sql(f"alter table public.venue_bookings add constraint {_CONSTRAINT} {definition}")
    assert _constraint_definition() == definition

    # WITH the constraint: exactly one confirm lands; the other is refused.
    # Usually with 23P01 (exclusion_violation): the loser's check finds the
    # winner's committed row. But if both UPDATEs reach the check before
    # either commits, each waits for the other and Postgres' deadlock
    # detector aborts one with 40P01 (deadlock_detected). Measured locally:
    # 25 of 30 races gave 23P01, 5 gave 40P01, and every race had exactly one
    # winner. Asserting only 23P01 would make this test fail about one run
    # in six; the guarantee is "exactly one", and that holds either way.
    # (The sequential refusal in the next test is always 23P01.)
    outcomes = _confirm_concurrently([first, second])
    winners = [o for o in outcomes if isinstance(o, dict)]
    losers = [o for o in outcomes if isinstance(o, APIError)]
    assert len(winners) == 1, outcomes
    assert len(losers) == 1, outcomes
    assert losers[0].code in ("23P01", "40P01"), losers[0]
    assert _confirmed_ids(f) == {winners[0]["id"]}


def test_releasing_a_confirmed_booking_frees_its_period(fixtures):
    """Only confirmed rows are in the constraint's scope, so a booking that
    leaves `confirmed` (rejected today; whatever a cancelled event's booking
    becomes later) stops blocking at once, with no extra handling."""
    f = fixtures
    day = datetime(2026, 11, 3, tzinfo=_SGT)
    held = f.pending_booking(day.replace(hour=10), day.replace(hour=12))
    waiting = f.pending_booking(day.replace(hour=11), day.replace(hour=13))

    supabase.table("venue_bookings").update({"status": "confirmed"}).eq("id", held).execute()
    with pytest.raises(APIError) as refused:
        supabase.table("venue_bookings").update({"status": "confirmed"}).eq("id", waiting).execute()
    assert refused.value.code == "23P01"

    supabase.table("venue_bookings").update({"status": "rejected"}).eq("id", held).execute()
    supabase.table("venue_bookings").update({"status": "confirmed"}).eq("id", waiting).execute()

    assert _confirmed_ids(f) == {waiting}


@pytest.mark.parametrize(
    ("other_start", "other_end", "clashes"),
    [
        ((8, 0), (10, 0), False),  # ends exactly when ours starts
        ((12, 0), (14, 0), False),  # starts exactly when ours ends
        ((8, 0), (10, 1), True),  # one minute over
        ((11, 0), (11, 30), True),  # inside ours
    ],
)
def test_report_and_constraint_agree_at_the_boundaries(fixtures, other_start, other_end, clashes):
    f = fixtures
    day = datetime(2026, 11, 4, tzinfo=_SGT)
    ours_start, ours_end = day.replace(hour=10), day.replace(hour=12)
    ours = f.pending_booking(ours_start, ours_end)
    other = f.pending_booking(
        day.replace(hour=other_start[0], minute=other_start[1]),
        day.replace(hour=other_end[0], minute=other_end[1]),
    )
    supabase.table("venue_bookings").update({"status": "confirmed"}).eq("id", other).execute()

    reported = [c["id"] for c in confirmed_clashes(f.venue_id, ours_start, ours_end, exclude_booking_id=ours)]
    try:
        supabase.table("venue_bookings").update({"status": "confirmed"}).eq("id", ours).execute()
        refused = False
    except APIError as exc:
        assert exc.code == "23P01", exc
        refused = True

    assert (reported == [other]) is clashes
    assert refused is clashes
