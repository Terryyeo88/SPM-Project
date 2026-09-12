"""
GET /me -- the authenticated caller's own id, email, name, and roles.

This is what the frontend routes by role and what Josiah's route guard
(IS-27) checks against. No policy check beyond authentication itself --
there is no resource here, and every authenticated user is unconditionally
entitled to know their own identity and roles. Protected by default like
every other route (see app/auth/context.py) -- nothing here opts out of
that with @public.
"""

from flask import Blueprint, jsonify

from app.auth.context import current_user

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
            }
        ),
        200,
    )
