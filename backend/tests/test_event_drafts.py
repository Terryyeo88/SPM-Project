"""Tests for saving incomplete event requests as drafts."""

from __future__ import annotations

from app.events.event_service import DRAFT_NAME, _draft_payload


def test_draft_payload_accepts_one_partial_field():
    """A draft may be saved with only one meaningful field filled in."""
    payload = _draft_payload({"description": "A conference draft."})

    assert payload["name"] == DRAFT_NAME
    assert payload["description"] == "A conference draft."


def test_draft_payload_preserves_partial_updates():
    """Saving a draft update preserves fields that were already stored."""
    payload = _draft_payload(
        {"description": "Updated description."},
        {
            "name": "Existing event",
            "purpose": "Existing purpose",
            "equipment": [],
        },
    )

    assert payload["name"] == "Existing event"
    assert payload["purpose"] == "Existing purpose"
    assert payload["description"] == "Updated description."
    assert payload["equipment_needed"] == {"equipment": []}


def test_draft_payload_normalizes_blank_date_and_time_fields_to_null():
    """Blank strings for the date/time fields (as an emptied HTML date/time
    input would submit) are normalized to None, not stored as empty
    strings -- same treatment as room_layout."""
    payload = _draft_payload(
        {
            "description": "A conference draft.",
            "preferred_start_date": "",
            "preferred_end_date": "",
            "preferred_start_time": "",
            "preferred_end_time": "",
        }
    )

    assert payload["preferred_start_date"] is None
    assert payload["preferred_end_date"] is None
    assert payload["preferred_start_time"] is None
    assert payload["preferred_end_time"] is None


def test_draft_payload_does_not_require_preferred_end_date():
    """preferred_end_date is mandatory for SUBMISSION (validate_event_payload
    with for_submission=True), but a draft never goes through that
    validation at all -- _draft_payload only needs at least one meaningful
    field, so a start date with no end date yet is a perfectly normal,
    still-in-progress draft."""
    payload = _draft_payload({"preferred_start_date": "2026-11-10"})

    assert payload["preferred_start_date"] == "2026-11-10"
    assert "preferred_end_date" not in payload


def test_draft_payload_does_not_enforce_24_hour_duration_limit():
    """The 24-hour max-duration rule lives in validate_event_payload, which
    drafts never call -- a draft may freely hold a multi-day date range
    while the organizer is still deciding on the details."""
    payload = _draft_payload(
        {
            "preferred_start_date": "2026-11-10",
            "preferred_end_date": "2026-11-20",
        }
    )

    assert payload["preferred_start_date"] == "2026-11-10"
    assert payload["preferred_end_date"] == "2026-11-20"
