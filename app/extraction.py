import ipaddress
import json
import re
import socket
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

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
    confidence: str = "NONE"
    warnings: list[str] = field(default_factory=list)


def _safe_hostname(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return False
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, None)}
        return bool(addresses) and all(
            not (address := ipaddress.ip_address(item)).is_private
            and not address.is_loopback
            and not address.is_link_local
            for item in addresses
        )
    except (OSError, ValueError):
        return False


def validate_fetch_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or not _safe_hostname(parsed.hostname):
        raise ValueError("Invalid or unsupported URL.")


def _source(hostname: str, path: str = "") -> str:
    host = hostname.lower()
    known = (
        ("linkedin.com", "LinkedIn"),
        ("naukri.com", "Naukri"),
        ("indeed.com", "Indeed"),
        ("lever.co", "Lever"),
        ("greenhouse.io", "Greenhouse"),
        ("workday.com", "Workday"),
    )
    for domain, label in known:
        if host == domain or host.endswith("." + domain):
            return label
    if host == "ycombinator.com" or host.endswith(".ycombinator.com"):
        return "Y Combinator"
    return "Company Careers"


def _clean(value: object, limit: int = 255) -> str | None:
    if not isinstance(value, str):
        return None
    if "<" in value and ">" in value:
        value = BeautifulSoup(value, "html.parser").get_text(" ")
    value = " ".join(value.split())
    return value[:limit] or None


def _add_warning(result: ExtractionResult, warning: str) -> None:
    if warning not in result.warnings:
        result.warnings.append(warning)


def _is_platform(hostname: str) -> bool:
    return any(hostname == domain or hostname.endswith("." + domain) for domain in ("linkedin.com", "indeed.com", "naukri.com"))


def _find_job_postings(value: object) -> list[dict]:
    found: list[dict] = []
    if isinstance(value, list):
        for item in value:
            found.extend(_find_job_postings(item))
    elif isinstance(value, dict):
        types = value.get("@type", [])
        types = types if isinstance(types, list) else [types]
        if "JobPosting" in types:
            found.append(value)
        for child in value.values():
            if isinstance(child, (dict, list)):
                found.extend(_find_job_postings(child))
    return found


def _location_text(value: object) -> str | None:
    if isinstance(value, list):
        values = [_location_text(item) for item in value]
        return ", ".join(item for item in values if item) or None
    if not isinstance(value, dict):
        return _clean(value)
    address = value.get("address", value)
    if isinstance(address, str):
        return _clean(address)
    if not isinstance(address, dict):
        return None
    parts = [address.get(key) for key in ("addressLocality", "addressRegion", "addressCountry")]
    return ", ".join(item for item in (_clean(part) for part in parts) if item) or None


def _extract_json_ld(soup: BeautifulSoup, result: ExtractionResult) -> bool:
    found = False
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            payload = json.loads(script.string or script.get_text())
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        postings = _find_job_postings(payload)
        if not postings:
            continue
        found = True
        posting = postings[0]
        result.role = result.role or _clean(posting.get("title"))
        organization = posting.get("hiringOrganization")
        if isinstance(organization, dict):
            result.company = result.company or _clean(organization.get("name"))
        result.location = result.location or _location_text(posting.get("jobLocation"))
        if not result.location and str(posting.get("jobLocationType", "")).upper() == "TELECOMMUTE":
            result.location = "Remote"
        result.description = result.description or _clean(posting.get("description"), 20_000)
    return found


def _extract_microdata(soup: BeautifulSoup, result: ExtractionResult) -> None:
    values: dict[str, str] = {}
    for element in soup.find_all(attrs={"itemprop": True}):
        prop = str(element.get("itemprop", "")).lower()
        if prop in {"title", "jobtitle", "hiringorganization", "joblocation", "description"}:
            value = element.get("content") or element.get("datetime") or element.get_text(" ")
            cleaned = _clean(value, 20_000 if prop == "description" else 255)
            if cleaned and prop not in values:
                values[prop] = cleaned
    result.role = result.role or values.get("title") or values.get("jobtitle")
    result.company = result.company or values.get("hiringorganization")
    result.location = result.location or values.get("joblocation")
    result.description = result.description or values.get("description")


def _find_application_job(value: object) -> dict[str, object] | None:
    if isinstance(value, list):
        for item in value:
            found = _find_application_job(item)
            if found:
                return found
    elif isinstance(value, dict):
        keys = {str(key).lower() for key in value}
        has_role = keys.intersection({"title", "jobtitle", "job_title", "positiontitle"})
        has_context = keys.intersection({"company", "companyname", "employer", "location", "joblocation"})
        if has_role and has_context:
            return value
        for child in value.values():
            found = _find_application_job(child)
            if found:
                return found
    return None


def _extract_application_state(soup: BeautifulSoup, result: ExtractionResult) -> None:
    for script in soup.find_all("script"):
        script_type = str(script.get("type", "")).lower()
        if script_type not in {"application/json", "application/ld+json"} and not script.get("data-state"):
            continue
        try:
            payload = json.loads(script.string or script.get_text())
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        job = _find_application_job(payload)
        if not job:
            continue
        result.role = result.role or _clean(next((job.get(key) for key in ("title", "jobTitle", "job_title", "positionTitle") if job.get(key)), None))
        result.company = result.company or _clean(next((job.get(key) for key in ("company", "companyName", "employer") if job.get(key)), None))
        result.location = result.location or _location_text(next((job.get(key) for key in ("location", "jobLocation") if job.get(key)), None))
        result.description = result.description or _clean(job.get("description"), 20_000)
        return


def _meta_values(soup: BeautifulSoup) -> dict[str, str]:
    values: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        key = tag.get("property") or tag.get("name")
        content = tag.get("content")
        if key and content:
            values[key.lower()] = content
    return values


def _extract_meta(soup: BeautifulSoup, result: ExtractionResult) -> None:
    values = _meta_values(soup)
    meta_title = _clean(values.get("og:title") or values.get("twitter:title"))
    title_role, title_company = _title_parts(meta_title or "")
    generic_meta = (meta_title or "").lower().startswith(("careers at ", "careers |", "jobs at ", "join "))
    result.role = result.role or title_role or (None if generic_meta else meta_title)
    result.company = result.company or title_company
    result.description = result.description or _clean(values.get("og:description") or values.get("twitter:description") or values.get("description"), 20_000)
    result.company = result.company or _clean(values.get("og:site_name"))


def _semantic_text(soup: BeautifulSoup, terms: tuple[str, ...]) -> str | None:
    normalized_terms = {term.lower().replace("-", "_") for term in terms}
    elements = soup.find_all(True)
    for exact in (True, False):
        for element in elements:
            markers = []
            for attribute in ("id", "class", "itemprop", "data-testid", "data-test", "aria-label"):
                raw = element.get(attribute, "")
                values = raw if isinstance(raw, list) else str(raw).split()
                markers.extend(value.lower().replace("-", "_") for value in values)
            match = any(marker in normalized_terms if exact else any(term in marker for term in normalized_terms) for marker in markers)
            if match:
                value = _clean(element.get_text(" "))
                if value and len(value) <= 255:
                    return value
    return None


def _title_parts(title: str) -> tuple[str | None, str | None]:
    parts = [part.strip() for part in re.split(r"\s*(?:\||\u2013|\u2014| - )\s*", title) if part.strip()]
    generic = {"careers", "jobs", "job", "careers page", "opportunities", "join our team", "open positions"}
    parts = [part for part in parts if part.lower() not in generic]
    if len(parts) < 2:
        return None, None
    role_words = ("engineer", "developer", "manager", "designer", "analyst", "scientist", "recruiter", "intern", "director", "specialist", "consultant", "lead")
    role_index = next((index for index, part in enumerate(parts) if any(word in part.lower() for word in role_words)), None)
    if role_index is not None:
        company = next((part for index, part in enumerate(parts) if index != role_index and part.lower() not in {"careers", "jobs"} and not _looks_like_location(part)), None)
        return parts[role_index], company
    return None, None


def _looks_like_location(value: str) -> bool:
    normalized = value.lower()
    return normalized in {"remote", "hybrid", "hyderabad", "bengaluru", "bangalore", "mumbai", "singapore", "dubai", "london", "new york"} or normalized.startswith(("remote ", "hybrid "))


def _hostname_company(hostname: str) -> str | None:
    if hostname.lower() in {"example.com", "example.org", "example.net"}:
        return None
    labels = [item for item in hostname.lower().split(".") if item not in {"www", "careers", "career", "jobs", "job", "work", "apply"}]
    if len(labels) < 2 or _is_platform(hostname):
        return None
    return labels[-2].replace("-", " ").title()


def _extract_html(soup: BeautifulSoup, result: ExtractionResult, hostname: str) -> None:
    title = _clean(soup.title.get_text(" ")) if soup.title is not None else None
    role, company = _title_parts(title or "")
    result.role = result.role or _semantic_text(soup, ("job-title", "jobtitle", "job_title", "position-title", "posting-title", "posting-headline", "job-header", "job-heading", "role-title", "position", "job-name")) or role
    result.company = result.company or _semantic_text(soup, ("company-name", "company", "employer", "hiring-organization")) or company
    result.location = result.location or _semantic_text(soup, ("job-location", "job_location", "location", "workplace"))
    if not result.role:
        heading = soup.find(["h1", "h2"])
        if heading is not None:
            candidate = _clean(heading.get_text(" "))
            if candidate and any(word in candidate.lower() for word in ("engineer", "developer", "manager", "designer", "analyst", "intern", "specialist")):
                result.role = candidate
    result.company = result.company or _hostname_company(hostname)


def _finalize(result: ExtractionResult, soup: BeautifulSoup, hostname: str) -> None:
    text = soup.get_text(" ").lower()
    if not result.role and any(marker in text for marker in ("enable javascript", "javascript is required", "loading...")):
        _add_warning(result, "This page appears to require JavaScript to expose job details.")
    if hostname.endswith("linkedin.com") and ("sign in" in text or "join linkedin" in text or not result.role):
        _add_warning(result, "LinkedIn did not expose enough public job metadata.")
    if not result.role and not result.company and not result.location:
        _add_warning(result, "Automatic extraction found no useful job details. You can enter them manually.")
    if result.role and result.company and result.location:
        result.confidence = "HIGH"
    elif result.role and result.company:
        result.confidence = "MEDIUM"
    elif result.role or result.company or result.location:
        result.confidence = "LOW"
    else:
        result.confidence = "NONE"


def extract_metadata(url: str) -> ExtractionResult:
    parsed = urlparse(url)
    result = ExtractionResult(source=_source(parsed.hostname or "", parsed.path))
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
                        raise ValueError("The job page returned an invalid redirect.")
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
                json_ld_found = _extract_json_ld(soup, result)
                _extract_microdata(soup, result)
                _extract_meta(soup, result)
                _extract_application_state(soup, result)
                _extract_html(soup, result, urlparse(current).hostname or "")
                _finalize(result, soup, urlparse(current).hostname or "")
                if not json_ld_found and result.confidence == "LOW":
                    _add_warning(result, "Automatic extraction found only partial information.")
                return result
            raise ValueError("Too many redirects.")
    except (httpx.HTTPError, ValueError, OSError):
        if result.source == "LinkedIn":
            _add_warning(result, "LinkedIn did not expose enough public metadata for automatic extraction.")
        else:
            _add_warning(result, "The job page could not be fetched. You can enter the job details manually.")
        result.confidence = "NONE"
        return result
