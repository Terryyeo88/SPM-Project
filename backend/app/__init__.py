"""
Flask application factory.
"""

from flask import Flask, jsonify
from flask_cors import CORS

from app.auth.context import register_auth_hooks
from app.config import Config
from app.shared.errors import AppError

# The Vue dev server's default origin (Vite). Credentials allowed because
# the frontend sends the Supabase-issued session token on each request.
_VUE_DEV_ORIGIN = "http://localhost:5173"


def create_app(config_override=None):
    app = Flask(__name__)
    app.config.from_object(config_override or Config)

    CORS(app, origins=[_VUE_DEV_ORIGIN], supports_credentials=True)

    _register_error_handlers(app)
    register_auth_hooks(app)
    _register_blueprints(app)

    return app


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(AppError)
    def handle_app_error(error: AppError):
        response = jsonify({"error": {"code": error.code, "message": error.message}})
        response.status_code = error.status_code
        return response

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):
        # Never leak the real exception message/type/traceback to the
        # caller -- only our own AppError subclasses are allowed to shape
        # a response. Full detail still goes to the server log.
        app.logger.exception("Unhandled exception")
        response = jsonify({"error": {"code": "internal_error", "message": "Internal server error"}})
        response.status_code = 500
        return response


def _register_blueprints(app: Flask) -> None:
    from app.health.routes import health_bp
    from app.me.routes import me_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(me_bp)
