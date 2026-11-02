"""
Safety review (IS-69): safety_service._notify_safety_review keeps its signature and hands its own
arguments, untouched, to notification_service.safety_review_changed. Who gets told what
is test_notification_service.py's job; this proves the wiring.

In its own file so that dropping the [PENDING ...] commit that rewired this
hook drops its test with it.
"""

from __future__ import annotations

import app.notifications.notification_service as notification_service
import app.safety.safety_service as safety_service


def test_safety_hook_passes_its_arguments_to_the_notification_service(monkeypatch):
    seen = []
    monkeypatch.setattr(notification_service, "safety_review_changed", lambda *a: seen.append(a))

    safety_service._notify_safety_review({"id": "s"}, "submitted")

    assert seen == [({"id": "s"}, "submitted")]
