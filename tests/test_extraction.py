from pathlib import Path

import httpx

from app.extraction import extract_metadata, validate_fetch_url

FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, body: str, content_type: str = "text/html"):
        self.content = body.encode()
        self.text = body
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        return None

    @property
    def is_redirect(self):
        return False


class FakeClient:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def get(self, url):
        return self.response


def result_for(monkeypatch, filename, url="https://example.com/jobs/1"):
    response = FakeResponse((FIXTURES / filename).read_text())
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: FakeClient(response))
    return extract_metadata(url)


def test_json_ld_graph_and_location(monkeypatch):
    result = result_for(monkeypatch, "jobposting_graph.html")
    assert result.role == "Backend Engineer"
    assert result.company == "Acme"
    assert result.location == "Hyderabad, Telangana"
    assert result.confidence == "HIGH"


def test_json_ld_array(monkeypatch):
    result = result_for(monkeypatch, "jobposting_array.html")
    assert result.role == "Data Analyst"
    assert result.company == "Northstar"
    assert result.location == "Singapore"


def test_metadata_and_html_fallbacks(monkeypatch):
    meta = result_for(monkeypatch, "jobposting_meta.html")
    assert meta.role == "Product Designer"
    assert meta.company == "Northstar"
    html = result_for(monkeypatch, "career_page.html")
    assert html.role == "Senior Developer"
    assert html.company == "Acme Technologies"
    assert html.location == "Remote / Hyderabad"


def test_blocked_and_javascript_pages_warn(monkeypatch):
    blocked = result_for(monkeypatch, "linkedin_blocked.html", "https://www.linkedin.com/jobs/view/1")
    assert any("LinkedIn" in warning for warning in blocked.warnings)
    shell = result_for(monkeypatch, "javascript_shell.html")
    assert any("JavaScript" in warning for warning in shell.warnings)


def test_malformed_json_ld_does_not_crash(monkeypatch):
    result = result_for(monkeypatch, "malformed_jsonld.html")
    assert result.description == "Manual review needed."
    assert result.confidence in {"LOW", "NONE"}


def test_unsafe_url_rejected():
    for url in ("file:///tmp/job", "http://localhost/job", "http://127.0.0.1/job"):
        try:
            validate_fetch_url(url)
        except ValueError:
            continue
        raise AssertionError(f"unsafe URL accepted: {url}")
