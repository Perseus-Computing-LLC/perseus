"""Tiny fixture used by the offline code-context benchmark."""
from auth import verify_token

def handle_request(token):
    return verify_token(token)
