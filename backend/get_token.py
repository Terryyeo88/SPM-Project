"""
Prints a real access token for a seeded test coordinator, by asking
Supabase directly -- there's no login page yet, so this is how you get a
token to manually test protected routes with curl/Invoke-WebRequest.

Run from backend/ with your venv active, in a SEPARATE terminal window
from the one running `flask --app wsgi run` (that one is busy serving
the server and won't accept more commands while it's running):

    python get_token.py
"""

from supabase_client import supabase

EMAIL = "coordinator1@example.com"  # Alice -- change to coordinator2/3 as needed
PASSWORD = "Password123!"

result = supabase.auth.sign_in_with_password({"email": EMAIL, "password": PASSWORD})
print(f"Signed in as: {EMAIL}")
print(f"User id: {result.user.id}")
print(f"Access token:\n{result.session.access_token}")
