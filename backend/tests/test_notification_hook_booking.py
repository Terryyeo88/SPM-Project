"""
Venue booking decision (IS-69): booking_service._notify_booking_decision keeps its signature and hands its own
arguments, untouched, to notification_service.venue_booking_decided. Who gets told what
is test_notification_service.py's job; this proves the wiring.

In its own file so that dropping the [PENDING ...] commit that rewired this
hook drops its test with it.
"""

from __future__ import annotations

import app.notifications.notification_service as notification_service
import app.venues.booking_service as booking_service


def test_booking_hook_passes_its_arguments_to_the_notification_service(monkeypatch):
    seen = []
    monkeypatch.setattr(notification_service, "venue_booking_decided", lambda *a: seen.append(a))

    booking_service._notify_booking_decision({"id": "b"}, "confirmed")

    assert seen == [({"id": "b"}, "confirmed")]
