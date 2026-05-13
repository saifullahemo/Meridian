import os

from fastapi import Header, HTTPException

API_KEY = os.getenv("PERSONAL_OS_API_KEY", "")
API_KEYS = os.getenv("PERSONAL_OS_API_KEYS", "")


def require_api_key(
    x_api_key: str = Header(default=""),
    authorization: str = Header(default=""),
) -> bool:
    """Require an API key only when PERSONAL_OS_API_KEY is configured."""
    if not API_KEY:
        return True
    bearer = ""
    if authorization.lower().startswith("bearer "):
        bearer = authorization[7:].strip()
    if x_api_key == API_KEY or bearer == API_KEY:
        return True
    if _scopes_for_key(x_api_key or bearer):
        return True
    raise HTTPException(status_code=401, detail="Valid API key required.")


def require_scope(scope: str):
    def dependency(x_api_key: str = Header(default=""), authorization: str = Header(default="")) -> bool:
        if not API_KEY and not API_KEYS:
            return True
        bearer = ""
        if authorization.lower().startswith("bearer "):
            bearer = authorization[7:].strip()
        key = x_api_key or bearer
        if API_KEY and key == API_KEY:
            return True
        scopes = _scopes_for_key(key)
        if "*" in scopes or scope in scopes:
            return True
        raise HTTPException(status_code=403, detail="API key lacks required scope: " + scope)

    return dependency


def _scopes_for_key(key: str) -> set[str]:
    if not key or not API_KEYS:
        return set()
    for entry in API_KEYS.split(";"):
        if not entry.strip() or ":" not in entry:
            continue
        candidate, scopes = entry.split(":", 1)
        if candidate == key:
            return {scope.strip() for scope in scopes.split(",") if scope.strip()}
    return set()
