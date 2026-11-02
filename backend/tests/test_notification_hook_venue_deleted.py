"""
Venue deleted (IS-69): venue_service._notify_venue_deleted keeps its signature and hands its own
arguments, untouched, to notification_service.venue_booking_released. Who gets told what
is test_notification_service.py's job; this proves the wiring.

In its own file so that dropping the [PENDING ...] commit that rewired this
hook drops its test with it.
"""

from __future__ import annotations

import app.notifications.notification_service as notification_service
import app.venues.venue_service as venue_service


def test_venue_deleted_hook_passes_its_arguments_to_the_notification_service(monkeypatch):
    seen = []
    monkeypatch.setattr(notification_service, "venue_booking_released", lambda *a: seen.append(a))

    venue_service._notify_venue_deleted({"booking_id": "b"}, {"id": "v"})

    assert seen == [({"booking_id": "b"}, {"id": "v"})]
