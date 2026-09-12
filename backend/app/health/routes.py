"""
Health check endpoints.

GET /health never touches Supabase. It must return 200 even with zero
credentials configured -- it's the first thing CI and teammates hit to
confirm the app boots at all.

GET /health/db runs one trivial Supabase query and reports whether the
database is actually reachable, returning 503 with a plain message
rather than propagating the underlying exception (missing credentials,
network failure, etc.) to the caller.
"""

from flask import Blueprint, current_app, jsonify

from app.auth.context import public
from app.extensions import supabase

health_bp = Blueprint("health", __name__, url_prefix="/health")


@health_bp.route("", methods=["GET"])
@public
def health():
    return jsonify({"status": "ok"}), 200


@health_bp.route("/db", methods=["GET"])
@public
def health_db():
    try:
        supabase.table("profiles").select("id").limit(1).execute()
    except Exception:
        current_app.logger.exception("Supabase health check failed")
        return (
            jsonify(
                {
                    "status": "unreachable",
                    "message": (
                        "Could not reach the database. Check SUPABASE_URL / "
                        "SUPABASE_SERVICE_ROLE_KEY and network connectivity."
                    ),
                }
            ),
            503,
        )
    return jsonify({"status": "ok"}), 200
