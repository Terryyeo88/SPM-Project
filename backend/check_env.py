"""
Diagnostic: confirms which Supabase project and which key type your .env
is actually using, without printing the real secret.

Handles both the legacy JWT-style keys (long strings starting with "eyJ",
role encoded inside as a JWT claim) and the newer short-string keys
(sb_publishable_... / sb_secret_...) that Supabase now issues.

Run from backend/ with your venv active:
    python check_env.py
"""

import base64
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

print("SUPABASE_URL:", url)

if not key:
    print("SUPABASE_SERVICE_ROLE_KEY is empty or missing from .env")
elif key.startswith("sb_secret_"):
    print("Key type: NEW format -- secret key (correct, backend/admin access, bypasses RLS)")
elif key.startswith("sb_publishable_"):
    print("Key type: NEW format -- publishable key (WRONG for the backend -- this is the "
          "public/frontend one, it will be blocked by RLS). Use the 'secret' key instead.")
elif key.startswith("eyJ"):
    try:
        payload = key.split(".")[1]
        padded = payload + "=" * (-len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded))
        role = decoded.get("role")
        if role == "service_role":
            print("Key type: LEGACY JWT -- service_role (correct)")
        else:
            print(f"Key type: LEGACY JWT -- role claim is '{role}' (WRONG -- should be service_role)")
    except Exception as e:
        print(f"Looked like a legacy JWT but couldn't decode it: {e}")
else:
    print("Key doesn't match any recognised Supabase key format -- "
          "double-check it was copied in full, with no extra quotes/spaces.")
