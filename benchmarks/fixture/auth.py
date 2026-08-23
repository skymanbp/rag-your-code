"""Authentication fixture for retrieval evaluation."""


def issue_session_token(user_id, signing_key):
    """Create a signed session token for an authenticated user."""
    return sign_jwt({"sub": user_id}, signing_key)


def verify_session_token(token, signing_key):
    """Validate a session token and reject expired or tampered credentials."""
    return decode_jwt(token, signing_key, verify_expiration=True)
