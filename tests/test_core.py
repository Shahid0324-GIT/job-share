import os

os.environ["DATABASE_URL"] = "sqlite:///./test-jobshare.db"
os.environ["SECRET_KEY"] = "test-secret"

from app.extraction import validate_fetch_url
from app.security import hash_token, new_token, normalize_url, token_matches


def test_normalize_url_removes_tracking_and_fragment():
    assert normalize_url("HTTPS://Example.com/jobs/123/?utm_source=x#details") == "https://example.com/jobs/123"


def test_url_guard_rejects_local_and_unsupported_urls():
    for url in ("http://localhost/job", "http://127.0.0.1/job", "file:///tmp/job"):
        try:
            validate_fetch_url(url)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted unsafe URL: {url}")


def test_friend_token_is_hashed_and_verifiable():
    token = new_token()
    stored = hash_token(token)
    assert token != stored
    assert token_matches(token, stored)
    assert not token_matches("wrong", stored)