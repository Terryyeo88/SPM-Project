"""
WSGI entrypoint.

    flask --app wsgi run

from backend/, with the venv active.
"""

from app import create_app

app = create_app()
