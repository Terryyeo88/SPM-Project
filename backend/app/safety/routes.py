"""HTTP routes for the Safety Officer's side of the Operational Feasibility
Check (Week 7 change #6):

  GET  /safety-reviews                        the dashboard (?status= filter)
  GET  /safety-reviews/<id>                   one review, with what to check
  POST /safety-reviews/<id>/approve           comment optional
  POST /safety-reviews/<id>/reject            comment required
  POST /safety-reviews/<id>/request-changes   comment required

The coordinator's side lives on the events blueprint
(app/events/routes.py): POST /events/<id>/safety-review to submit, GET
/events/<id>/safety-reviews for a session's history, and the confirm
route's "only once approved" gate.
"""

from __future__ import annotations

from types import SimpleNamespace

from flask import Blueprint, jsonify, request

from app.auth.context import current_user
from app.authz.actions import (
    SAFETY_REVIEW_APPROVE,
    SAFETY_REVIEW_LIST,
    SAFETY_REVIEW_REJECT,
    SAFETY_REVIEW_REQUEST_CHANGES,
    SAFETY_REVIEW_VIEW,
)
from app.authz.decorators import require
from app.safety.safety_service import decide_review, get_review, list_reviews, review_detail

safety_bp = Blueprint("safety", __name__, url_prefix="/safety-reviews")


def load_review(review_id: str) -> SimpleNamespace:
    """Loader for @require: the review as a SafetyReviewLike (see
    app.authz.protocol). get_review raises NotFoundError for a missing row,
    so a missing review and a hidden one give the same 404."""
    return SimpleNamespace(**get_review(review_id))


def _comment() -> object:
    body = request.get_json(silent=True) or {}
    return body.get("comment")


@safety_bp.route("", methods=["GET"])
@require(SAFETY_REVIEW_LIST)
def list_safety_reviews_route():
    return jsonify(list_reviews(current_user(), request.args.get("status"))), 200


@safety_bp.route("/<review_id>", methods=["GET"])
@require(SAFETY_REVIEW_VIEW, loader=lambda review_id: load_review(review_id))
def get_safety_review_route(review, review_id):
    return jsonify(review_detail(review)), 200


@safety_bp.route("/<review_id>/approve", methods=["POST"])
@require(SAFETY_REVIEW_APPROVE, loader=lambda review_id: load_review(review_id))
def approve_safety_review_route(review, review_id):
    return jsonify(decide_review(review_id, review, "approved", current_user().id, _comment())), 200


@safety_bp.route("/<review_id>/reject", methods=["POST"])
@require(SAFETY_REVIEW_REJECT, loader=lambda review_id: load_review(review_id))
def reject_safety_review_route(review, review_id):
    return jsonify(decide_review(review_id, review, "rejected", current_user().id, _comment())), 200


@safety_bp.route("/<review_id>/request-changes", methods=["POST"])
@require(SAFETY_REVIEW_REQUEST_CHANGES, loader=lambda review_id: load_review(review_id))
def request_changes_safety_review_route(review, review_id):
    return jsonify(decide_review(review_id, review, "changes_requested", current_user().id, _comment())), 200
