import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings


@dataclass
class ExtractionResult:
    company: str | None = None
    role: str | None = None
    location: str | None = None
    description: str | None = None
    source: str = "Company Careers"
    confidence: str = "low"
    warnings: list[str] = field(default_factory=list)


def _safe_hostname(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return False
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, None)}
        return bool(addresses) and all(not ipaddress.ip_address(address).is_private and not ipaddress.ip_address(address).is_loopback and not ipaddress.ip_address(address).is_link_local for address in addresses)
    except (OSError, ValueError):
        return False


def validate_fetch_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or not _safe_hostname(parsed.hostname):
        raise ValueError("Invalid or unsupported URL.")


def _source(hostname: str) -> str:
    host = hostname.lower()
    for domain, label in (("linkedin.com", "LinkedIn"), ("naukri.com", "Naukri"), ("indeed.com", "Indeed"), ("lever.co", "Lever"), ("greenhouse.io", "Greenhouse"), ("workday.com", "Workday")):
        if host == domain or host.endswith("." + domain):
            return label
    return "Company Careers"


def _clean(value: object, limit: int = 255) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value[:limit] or None


def extract_metadata(url: str) -> ExtractionResult:
    parsed = urlparse(url)
    result = ExtractionResult(source=_source(parsed.hostname or ""))
    try:
        validate_fetch_url(url)
        timeout = httpx.Timeout(10.0, connect=5.0)
        headers = {"User-Agent": "JobShare/1.0 metadata fetcher"}
        with httpx.Client(timeout=timeout, follow_redirects=False, headers=headers) as client:
            current = url
            for _ in range(3):
                response = client.get(current)
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        break
                    from urllib.parse import urljoin
                    current = urljoin(current, location)
                    validate_fetch_url(current)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if "html" not in content_type:
                    raise ValueError("The job page was not HTML.")
                if len(response.content) > get_settings().max_fetch_bytes:
                    raise ValueError("The job page is too large.")
                soup = BeautifulSoup(response.text[: get_settings().max_fetch_bytes], "html.parser")
                _extract_json_ld(soup, result)
                _extract_meta(soup, result)
                if not result.role and soup.title:
                    result.role = _clean(soup.title.get_text(" "))
                heading = soup.find("h1")
                if not result.role and heading is not None:
                    result.role = _clean(heading.get_text(" "))
                result.confidence = "high" if result.role and result.company else "medium" if result.role else "low"
                return result
            raise ValueError("Too many redirects.")
    except (httpx.HTTPError, ValueError, OSError) as exc:
        result.warnings.append("The job page could not be fetched. You can enter the job details manually.")
        return result


def _extract_json_ld(soup: BeautifulSoup, result: ExtractionResult) -> None:
    import json
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            payload = json.loads(script.string or script.get_text())
        except (TypeError, ValueError):
            continue
        entries = payload if isinstance(payload, list) else [payload]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("@type") == "JobPosting" or "JobPosting" in entry.get("@type", []):
                result.role = result.role or _clean(entry.get("title"))
                organization = entry.get("hiringOrganization") or {}
                result.company = result.company or _clean(organization.get("name") if isinstance(organization, dict) else None)
                location = entry.get("jobLocation") or {}
                if isinstance(location, list):
                    location = location[0] if location else {}
                address = location.get("address") if isinstance(location, dict) else {}
                result.location = result.location or _clean(address.get("addressLocality") if isinstance(address, dict) else None)
                result.description = result.description or _clean(entry.get("description"), 20_000)


def _extract_meta(soup: BeautifulSoup, result: ExtractionResult) -> None:
    values = {}
    for tag in soup.find_all("meta"):
        key = tag.get("property") or tag.get("name")
        content = tag.get("content")
        if key and content:
            values[key.lower()] = content
    result.role = result.role or _clean(values.get("og:title") or values.get("twitter:title"))
    result.description = result.description or _clean(values.get("og:description") or values.get("description"), 20_000)
    result.company = result.company or _clean(values.get("og:site_name"))
