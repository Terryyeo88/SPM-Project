"""Live Supabase integration tests for notifications (IS-69) -- what the
unit tests' in-memory fake can't prove:

- the RLS policy: a signed-in user reading notifications directly (going
  around Flask, as the browser's publishable key could) sees only their own,
  and can't write any
- the conditioned read update keeps the first read time, against Postgres
- the table's own checks (a link is both halves or neither)
- a fan-out to every Safety Officer reads real user_roles

Needs a local stack (`npx supabase start && npx supabase db reset`), like
every other integration test.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from postgrest.exceptions import APIError
from supabase import create_client

import app.notifications.notification_service as service
from app.extensions import supabase

pytestmark = pytest.mark.integration

_PASSWORD = "Password123!-throwaway-test-account"


def _create_user(roles: list[str]) -> str:
    email = f"notification-test-{uuid.uuid4()}@example.com"
    created = supabase.auth.admin.create_user({"email": email, "password": _PASSWORD, "email_confirm": True})
    user_id = created.user.id
    supabase.table("profiles").insert({"id": user_id, "name": "Notification Test User", "email": email}).execute()
    for role in roles:
        supabase.table("user_roles").insert({"user_id": user_id, "role": role}).execute()
    return user_id


def _delete_user(user_id: str) -> None:
    # Their notifications go with the profile (on delete cascade).
    supabase.table("user_roles").delete().eq("user_id", user_id).execute()
    supabase.table("profiles").delete().eq("id", user_id).execute()
    supabase.auth.admin.delete_user(user_id)


def _signed_in_as(user_id: str):
    """A client signed in as this user, on its OWN client instance (see
    test_jwt_integration.py for why never the shared one): requests carry
    their JWT, so the database applies the `authenticated` role and RLS."""
    email = supabase.table("profiles").select("email").eq("id", user_id).single().execute().data["email"]
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    client.auth.sign_in_with_password({"email": email, "password": _PASSWORD})
    return client


def _mine(user_id: str) -> list[dict]:
    return supabase.table("notifications").select("*").eq("recipient_id", user_id).execute().data


@pytest.fixture
def users():
    created: list[str] = []

    def make(roles=("event_coordinator",)):
        created.append(_create_user(list(roles)))
        return created[-1]

    try:
        yield make
    finally:
        for user_id in created:
            _delete_user(user_id)


# -- RLS -------------------------------------------------------------------------


def test_a_signed_in_user_reads_only_their_own_notifications_directly(users):
    alice, bob = users(), users()
    service.notify([alice], "test", "for alice")
    service.notify([bob], "test", "for bob")

    seen = _signed_in_as(alice).table("notifications").select("recipient_id, message").execute().data

    assert seen == [{"recipient_id": alice, "message": "for alice"}]


def test_a_signed_in_user_cannot_write_notifications_directly(users):
    alice = users()
    service.notify([alice], "test", "for alice")
    client = _signed_in_as(alice)

    # No update policy: RLS matches no row, so nothing changes.
    client.table("notifications").update({"read_at": datetime.now(UTC).isoformat()}).eq("recipient_id", alice).execute()
    assert _mine(alice)[0]["read_at"] is None

    # No insert policy: refused outright.
    with pytest.raises(APIError) as refused:
        client.table("notifications").insert({"recipient_id": alice, "type": "x", "message": "forged"}).execute()
    assert refused.value.code == "42501"
    assert len(_mine(alice)) == 1


# -- the read side, against Postgres ----------------------------------------------


def test_mark_read_keeps_the_first_read_time_and_mark_all_is_scoped(users):
    alice, bob = users(), users()
    service.notify([alice], "test", "one")
    service.notify([alice], "test", "two")
    service.notify([bob], "test", "bob's")
    first = service.list_notifications(alice)[-1]

    marked = service.mark_read(first["id"], alice)
    again = service.mark_read(first["id"], alice)

    assert marked["read_at"] is not None
    assert again["read_at"] == marked["read_at"]
    assert service.unread_count(alice) == 1
    assert service.mark_all_read(alice) == 1
    assert (service.unread_count(alice), service.unread_count(bob)) == (0, 1)
    assert service.get_notification(first["id"])["read_at"] == marked["read_at"]


def test_list_is_newest_first(users):
    alice = users()
    for message in ("first", "second", "third"):
        service.notify([alice], "test", message)

    assert [row["message"] for row in service.list_notifications(alice)] == ["third", "second", "first"]


def test_a_link_is_both_halves_or_neither(users):
    alice = users()
    with pytest.raises(APIError) as refused:
        supabase.table("notifications").insert(
            {"recipient_id": alice, "type": "test", "message": "half a link", "entity_type": "event"}
        ).execute()
    assert refused.value.code == "23514"


# -- fan-out against real rows ----------------------------------------------------------
# A real story action writing a real notification (rejecting an equipment
# request) is in test_notification_hook_equipment.py, with the hook it goes
# through. session_with_request is shared with it.


@pytest.fixture
def session_with_request(users):
    organiser, coordinator_before, coordinator_now = users(["event_organizer"]), users(), users()
    event = (
        supabase.table("events")
        .insert(
            {
                "name": f"Notification Test {uuid.uuid4()}",
                "organizer_id": organiser,
                "coordinator_id": coordinator_now,
                "status": "planning",
            }
        )
        .execute()
        .data[0]
    )
    start = datetime.now(UTC) + timedelta(days=30)
    request = (
        supabase.table("equipment_requests")
        .insert(
            {
                "event_id": event["id"],
                "requested_by": coordinator_before,
                "needed_start": start.isoformat(),
                "needed_end": (start + timedelta(hours=4)).isoformat(),
            }
        )
        .execute()
        .data[0]
    )
    try:
        yield event, request, coordinator_before, coordinator_now
    finally:
        supabase.table("equipment_requests").delete().eq("id", request["id"]).execute()
        supabase.table("events").delete().eq("id", event["id"]).execute()


def test_a_safety_submission_reaches_every_safety_officer(session_with_request, users):
    event = session_with_request[0]
    officer_a, officer_b = users(["safety_officer"]), users(["safety_officer"])
    review_id = str(uuid.uuid4())

    service.safety_review_changed({"id": review_id, "event_id": event["id"]}, "submitted")

    for officer in (officer_a, officer_b):
        [row] = _mine(officer)
        assert (row["type"], row["entity_type"], row["entity_id"]) == (
            service.SAFETY_REVIEW_SUBMITTED,
            "safety_review",
            review_id,
        )
