"""
HTTP routes for Attendee Registration (Justin). Attendee only.

  GET    /registrations/open                 upcoming sessions open to attendees
                                             (confirmed, registration enabled),
                                             public fields + places left
  GET    /registrations/mine                 the caller's registrations, with
                                             status and waiting-list position
  GET    /registrations/sessions/<event_id>  one public session + places left +
                                             the caller's registration (or null)
  POST   /registrations/<event_id>           register. Body: {"email", "phone",
                                             "notify_email", "notify_sms",
                                             "include_organisation", "notes"?}
                                             -> 201; status "confirmed" or
                                             "waitlisted"
  DELETE /registrations/<event_id>           withdraw / leave the waiting list
                                             -> {"withdrawn": true, "promoted": bool}

NOT built (see docs/open-questions.md): notifying the attendee
(Notification story) and organiser/coordinator views of who registered.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.auth.context import current_user
from app.authz.actions import EVENT_REGISTER, EVENT_VIEW_PUBLIC, REGISTRATION_LIST, REGISTRATION_WITHDRAW
from app.authz.decorators import require
from app.registrations.registration_service import (
    get_session,
    list_my_registrations,
    list_open_sessions,
    register,
    withdraw,
)

registrations_bp = Blueprint("registrations", __name__, url_prefix="/registrations")


@registrations_bp.route("/open", methods=["GET"])
@require(REGISTRATION_LIST)
def list_open_route():
    return jsonify(list_open_sessions()), 200


@registrations_bp.route("/mine", methods=["GET"])
@require(REGISTRATION_LIST)
def list_mine_route():
    return jsonify(list_my_registrations(current_user().id)), 200


@registrations_bp.route("/sessions/<event_id>", methods=["GET"])
@require(EVENT_VIEW_PUBLIC, loader=lambda event_id: load_session(event_id))
def get_session_route(event, event_id):
    return jsonify(get_session(event.id, current_user().id)), 200


@registrations_bp.route("/<event_id>", methods=["POST"])
@require(EVENT_REGISTER, loader=lambda event_id: load_session(event_id))
def register_route(event, event_id):
    registration = register(event, current_user().id, request.get_json(silent=True) or {})
    return jsonify(registration), 201


@registrations_bp.route("/<event_id>", methods=["DELETE"])
@require(REGISTRATION_WITHDRAW, loader=lambda event_id: load_session(event_id))
def withdraw_route(event, event_id):
    return jsonify(withdraw(event.id, current_user().id)), 200


def load_session(event_id: str):
    """Same loader as the events routes (a missing session is a 404).
    Looked up at call time so tests can monkeypatch either module."""
    from app.events import routes as events_routes

    return events_routes.load_event(event_id)
