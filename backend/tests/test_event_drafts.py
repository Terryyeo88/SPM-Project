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
