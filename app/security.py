import hashlib
import hmac
import secrets
import time
from urllib.parse import urlparse

from app.config import get_settings


def hash_token(token: str) -> str:
    return hmac.new(get_settings().secret_key.encode(), token.encode(), hashlib.sha256).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_matches(token: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), stored_hash)


def make_session(value: str, ttl: int = 86400) -> str:
    expires = str(int(time.time()) + ttl)
    payload = f"{value}.{expires}"
    signature = hmac.new(get_settings().secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def valid_session(value: str | None, expected: str) -> bool:
    try:
        payload, expires, signature = value.split(".")
        if int(expires) < int(time.time()) or payload != expected:
            return False
        expected_signature = hmac.new(get_settings().secret_key.encode(), f"{payload}.{expires}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected_signature)
    except (AttributeError, ValueError):
        return False


def normalize_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Invalid or unsupported URL.")
    tracking = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid"}
    from urllib.parse import parse_qsl, urlencode, urlunparse
    query = urlencode([(key, item) for key, item in parse_qsl(parsed.query) if key.lower() not in tracking])
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", query, ""))
