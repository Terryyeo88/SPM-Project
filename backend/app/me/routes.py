"""
GET /me -- the authenticated caller's own id, email, name, and roles,
plus their contact details and communication preferences (IS-68):
phone, organisation, notify_email, notify_sms -- each null until given.

This is what the frontend routes by role and what Josiah's route guard
(IS-27) checks against. No policy check beyond authentication itself --
there is no resource here, and every authenticated user is unconditionally
entitled to know their own identity and roles. Protected by default like
every other route (see app/auth/context.py) -- nothing here opts out of
that with @public. (That GET /me has no @require at all is logged in
docs/open-questions.md, IS-68; deliberately not changed by IS-68.)

PATCH /me/profile -- the caller updates their OWN contact details and
preferences (IS-68). The profile is the token's user, never an id from
the URL or body: there is no id to give, and a body naming "id" or
"email" is a 400. See app/me/profile_service.py and rule_profile_edit_own.
"""

from flask import Blueprint, jsonify, request

from app.auth.context import current_user
from app.authz.actions import PROFILE_EDIT_OWN
from app.authz.decorators import require
from app.me.profile_service import get_contact, update_own_profile

me_bp = Blueprint("me", __name__, url_prefix="/me")


@me_bp.route("", methods=["GET"])
def me():
    user = current_user()
    return (
        jsonify(
            {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "roles": sorted(user.roles),
                **get_contact(user.id),
            }
        ),
        200,
    )


@me_bp.route("/profile", methods=["PATCH"])
@require(PROFILE_EDIT_OWN)
def update_profile():
    user = current_user()
    return jsonify(update_own_profile(user.id, request.get_json(silent=True))), 200
