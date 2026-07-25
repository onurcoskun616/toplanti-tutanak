"""Per-meeting edit-token helpers (no user accounts exist in this app)."""
import hashlib
import hmac
import secrets


def generate_edit_token() -> str:
    return secrets.token_urlsafe(24)


def hash_edit_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def verify_edit_token(candidate: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_edit_token(candidate), stored_hash)
