"""HTTP routes for the caller's own in-app notifications (IS-69):

  GET  /notifications                {"notifications": [...], "unread_count": n}
                                     newest first; ?unread=true for unread only
  GET  /notifications/unread-count   {"unread_count": n} -- the bell's poll
  POST /notifications/<id>/read      mark one read (recipient only; else 404)
  POST /notifications/read-all       mark every one of the caller's read

Every authenticated role has notifications, so nothing here is role-gated;
every query is scoped to the caller (see rule_notification_list). Nothing
is written through these routes except read_at: notifications are created
by the stories that notify (app.notifications.notification_service).
"""

from __future__ import annotations

from types import SimpleNamespace

from flask import Blueprint, jsonify, request

from app.auth.context import current_user
from app.authz.actions import NOTIFICATION_LIST, NOTIFICATION_MARK_ALL_READ, NOTIFICATION_MARK_READ
from app.authz.decorators import require
from app.notifications.notification_service import (
    get_notification,
    list_notifications,
    mark_all_read,
    mark_read,
    unread_count,
)

notifications_bp = Blueprint("notifications", __name__, url_prefix="/notifications")


def load_notification(notification_id: str) -> SimpleNamespace:
    """Loader for @require: the notification as a NotificationLike (see
    app.authz.protocol). get_notification raises NotFoundError for a missing
    row, so a missing notification and someone else's give the same 404."""
    return SimpleNamespace(**get_notification(notification_id))


@notifications_bp.route("", methods=["GET"])
@require(NOTIFICATION_LIST)
def list_notifications_route():
    user_id = current_user().id
    return jsonify(
        {
            "notifications": list_notifications(user_id, request.args.get("unread")),
            "unread_count": unread_count(user_id),
        }
    ), 200


@notifications_bp.route("/unread-count", methods=["GET"])
@require(NOTIFICATION_LIST)
def unread_count_route():
    return jsonify({"unread_count": unread_count(current_user().id)}), 200


@notifications_bp.route("/<notification_id>/read", methods=["POST"])
@require(NOTIFICATION_MARK_READ, loader=lambda notification_id: load_notification(notification_id))
def mark_read_route(notification, notification_id):
    user_id = current_user().id
    return jsonify({"notification": mark_read(notification_id, user_id), "unread_count": unread_count(user_id)}), 200


@notifications_bp.route("/read-all", methods=["POST"])
@require(NOTIFICATION_MARK_ALL_READ)
def mark_all_read_route():
    user_id = current_user().id
    return jsonify({"marked_read": mark_all_read(user_id), "unread_count": unread_count(user_id)}), 200
