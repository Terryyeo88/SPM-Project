"""
Coordinator assignment (IS-69): coordinator_service._notify_coordinator_assigned keeps its signature and hands its own
arguments, untouched, to notification_service.coordinator_assigned. Who gets told what
is test_notification_service.py's job; this proves the wiring.

In its own file so that dropping the [PENDING ...] commit that rewired this
hook drops its test with it.
"""

from __future__ import annotations

import app.events.coordinator_service as coordinator_service
import app.notifications.notification_service as notification_service


def test_coordinator_hook_passes_its_arguments_to_the_notification_service(monkeypatch):
    seen = []
    monkeypatch.setattr(notification_service, "coordinator_assigned", lambda *a: seen.append(a))

    coordinator_service._notify_coordinator_assigned({"id": "e"}, {"id": "c"})

    assert seen == [({"id": "e"}, {"id": "c"})]
