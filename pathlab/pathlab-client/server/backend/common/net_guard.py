"""Outbound HTTP egress guard for user-provided URLs."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx


class EgressDeniedError(ValueError):
    """Raised when a URL targets a forbidden network location."""


_ALLOWED_SCHEMES = {"http", "https"}
_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}


def _is_forbidden_ip(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return True
    return any(
        (
            ip.is_loopback,
            ip.is_link_local,
            ip.is_private,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )


def validate_external_url(url: str) -> str:
    """Validate a URL before outbound fetches.

    Allows only public http/https targets. Hostnames are resolved and every
    returned address must be public; this prevents obvious SSRF to localhost,
    RFC1918 networks, link-local metadata services, and ULA IPv6 addresses.
    """
    text = str(url or "").strip()
    parsed = urlparse(text)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise EgressDeniedError("Only http/https URLs are allowed")
    if not parsed.hostname:
        raise EgressDeniedError("URL host is required")
    host = parsed.hostname
    try:
        ipaddress.ip_address(host)
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise EgressDeniedError(f"URL host could not be resolved: {host}") from exc
        addresses = {info[4][0] for info in infos if info and info[4]}
    else:
        addresses = {host}
    if not addresses or any(_is_forbidden_ip(address) for address in addresses):
        raise EgressDeniedError("URL host resolves to a forbidden network address")
    return text


def resolve_redirect_url(current_url: str, location: str) -> str:
    """Resolve and validate one redirect Location header."""
    return validate_external_url(urljoin(str(current_url), str(location or "")))


async def guarded_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_redirects: int = 5,
    **kwargs,
) -> httpx.Response:
    """GET with manual redirect validation on every hop."""
    next_url = validate_external_url(url)
    for _ in range(max_redirects + 1):
        response = await client.get(next_url, follow_redirects=False, **kwargs)
        if response.status_code not in _REDIRECT_STATUS_CODES:
            return response
        location = response.headers.get("location")
        if not location:
            return response
        next_url = resolve_redirect_url(str(response.url), location)
    raise EgressDeniedError("Too many redirects")


async def guarded_head(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_redirects: int = 5,
    **kwargs,
) -> httpx.Response:
    """HEAD with manual redirect validation on every hop."""
    next_url = validate_external_url(url)
    for _ in range(max_redirects + 1):
        response = await client.head(next_url, follow_redirects=False, **kwargs)
        if response.status_code not in _REDIRECT_STATUS_CODES:
            return response
        location = response.headers.get("location")
        if not location:
            return response
        next_url = resolve_redirect_url(str(response.url), location)
    raise EgressDeniedError("Too many redirects")


def guarded_requests_get(session, url: str, *, max_redirects: int = 5, **kwargs):
    """Synchronous GET with manual redirect validation for requests-like sessions."""
    next_url = validate_external_url(url)
    for _ in range(max_redirects + 1):
        response = session.get(next_url, allow_redirects=False, **kwargs)
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code not in _REDIRECT_STATUS_CODES:
            return response
        headers = getattr(response, "headers", {}) or {}
        location = headers.get("location") or headers.get("Location")
        if not location:
            return response
        next_url = resolve_redirect_url(next_url, location)
    raise EgressDeniedError("Too many redirects")


def guarded_requests_post(session, url: str, *, max_redirects: int = 5, **kwargs):
    """Synchronous POST with manual redirect validation for requests-like sessions."""
    next_url = validate_external_url(url)
    for _ in range(max_redirects + 1):
        response = session.post(next_url, allow_redirects=False, **kwargs)
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code not in _REDIRECT_STATUS_CODES:
            return response
        headers = getattr(response, "headers", {}) or {}
        location = headers.get("location") or headers.get("Location")
        if not location:
            return response
        next_url = resolve_redirect_url(next_url, location)
    raise EgressDeniedError("Too many redirects")
