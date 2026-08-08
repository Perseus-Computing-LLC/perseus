"""Worker calls the API handler."""
from api import handle_request

def run_worker(token):
    return handle_request(token)
