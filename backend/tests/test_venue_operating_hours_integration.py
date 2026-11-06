"""Live Supabase tests for IS-11 AC5 (Nawaz, 6 Nov): what the unit tests'
fakes (test_venue_catalogue_crud.py, test_booking_operating_hours.py) can't
prove.

  - Venue Staff's opening and closing times round-trip through the real
    venues.operating_hours_start/end `time` columns (set, edited, cleared).
  - The database's own pair check (venues_operating_hours_consistent, from
    20261007000000_venue_calendar.sql) still holds behind the service's.
  - A new booking request outside the hours is refused and writes nothing;
    one inside them is stored; an existing booking is left alone when the
    hours later change.

Reuses test_venue_catalogue_crud_integration.py's throwaway fixtures, which
remove every user, venue and event they create. Skipped automatically
without a local Supabase (see conftest.py).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

from app.extensions import supabase
from app.shared.errors import ValidationError
from app.venues import venue_service as service
from app.venues.booking_service import create_booking_request
from tests.test_venue_catalogue_crud_integration import coordinator, f  # noqa: F401

pytestmark = pytest.mark.integration


def _stored_hours(venue_id):
    venue = service.get_venue(venue_id)
    return venue["operating_hours_start"], venue["operating_hours_end"]


def _bookings(venue_id):
    return supabase.table("venue_bookings").select("*").eq("venue_id", venue_id).execute().data


def test_hours_set_on_create_are_stored(f):  # noqa: F811
    venue = f.venue(operating_hours_start="08:00", operating_hours_end="20:00")

    assert _stored_hours(venue["id"]) == ("08:00:00", "20:00:00")


def test_hours_can_be_edited_and_cleared(f):  # noqa: F811
    venue = f.venue(operating_hours_start="08:00", operating_hours_end="20:00")

    service.update_venue(venue["id"], {"operating_hours_end": "22:30"})
    assert _stored_hours(venue["id"]) == ("08:00:00", "22:30:00")

    service.update_venue(venue["id"], {"operating_hours_start": "", "operating_hours_end": ""})
    assert _stored_hours(venue["id"]) == (None, None)


def test_the_database_still_refuses_half_a_window(f):  # noqa: F811
    venue = f.venue(operating_hours_start="08:00", operating_hours_end="20:00")

    with pytest.raises(APIError):
        supabase.table("venues").update({"operating_hours_end": None}).eq("id", venue["id"]).execute()
    assert _stored_hours(venue["id"]) == ("08:00:00", "20:00:00")


def test_a_request_outside_the_hours_is_refused_and_writes_nothing(f, coordinator):  # noqa: F811
    # The fixture event runs 09:00-12:00; with 30 minutes of setup the
    # booking would start at 08:30, before a 09:00 opening.
    venue = f.venue(operating_hours_start="09:00", operating_hours_end="20:00")
    event = f.event(coordinator)

    with pytest.raises(ValidationError, match="outside those hours"):
        create_booking_request(SimpleNamespace(**event), venue["id"], coordinator)
    assert _bookings(venue["id"]) == []


def test_a_request_inside_the_hours_is_stored(f, coordinator):  # noqa: F811
    venue = f.venue(operating_hours_start="08:00", operating_hours_end="20:00")
    event = f.event(coordinator)

    booking = create_booking_request(SimpleNamespace(**event), venue["id"], coordinator)

    assert [row["id"] for row in _bookings(venue["id"])] == [booking["id"]]


def test_changing_the_hours_leaves_an_existing_booking_alone(f, coordinator):  # noqa: F811
    venue = f.venue(operating_hours_start="08:00", operating_hours_end="20:00")
    booking = f.booking(f.event(coordinator), venue, coordinator, status="pending")

    service.update_venue(venue["id"], {"operating_hours_start": "10:00", "operating_hours_end": "18:00"})

    [stored] = _bookings(venue["id"])
    assert (stored["status"], stored["booking_start"]) == ("pending", booking["booking_start"])
