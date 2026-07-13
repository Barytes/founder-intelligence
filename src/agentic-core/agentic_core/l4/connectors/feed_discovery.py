from __future__ import annotations

from html.parser import HTMLParser
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

from agentic_core.l4.connectors.base import (
    ConnectorLimits,
    HTTPClient,
    NetworkPolicyError,
    UrllibHTTPClient,
    validate_public_url,
)


FEED_CONTENT_TYPES = {
    "application/rss+xml",
    "application/atom+xml",
}
PROXY_BENCHMARK_NETWORK = ipaddress.ip_network("198.18.0.0/15")


def validate_discovery_url(url: str, *, resolver=socket.getaddrinfo) -> str:
    """Validate a discovered URL while supporting the host's transparent proxy.

    Public domains resolve to RFC 2544 benchmark addresses in this environment.
    Only a hostname (never a literal IP) whose complete resolution is inside that
    proxy range receives the exception. Localhost and other non-global ranges
    remain rejected.
    """

    try:
        return validate_public_url(url, resolver=resolver)
    except NetworkPolicyError:
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").lower()
        if (
            parsed.scheme not in {"http", "https"}
            or not hostname
            or hostname == "localhost"
            or hostname.endswith(".localhost")
        ):
            raise
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            raise
        try:
            addresses = {
                ipaddress.ip_address(row[4][0])
                for row in resolver(
                    hostname,
                    parsed.port or (443 if parsed.scheme == "https" else 80),
                )
            }
        except OSError:
            raise
        if addresses and all(
            address.is_global or address in PROXY_BENCHMARK_NETWORK
            for address in addresses
        ):
            return url
        raise


class _AlternateFeedParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.href is not None or tag.lower() != "link":
            return
        values = {key.lower(): (value or "") for key, value in attrs}
        rel = {part.lower() for part in values.get("rel", "").split()}
        content_type = values.get("type", "").split(";", 1)[0].strip().lower()
        if "alternate" in rel and content_type in FEED_CONTENT_TYPES and values.get("href"):
            self.href = values["href"]


def discover_alternate_feed(
    page_url: str,
    *,
    http_client: HTTPClient | None = None,
    limits: ConnectorLimits = ConnectorLimits(max_bytes=500_000, max_items=5),
) -> str | None:
    """Resolve a public HTML page to a declared feed without ingesting HTML."""

    response = (
        http_client
        or UrllibHTTPClient(url_validator=validate_discovery_url)
    ).get(page_url, limits)
    content_type = response.headers.get("content-type", "").lower()
    if content_type and "html" not in content_type:
        return None
    parser = _AlternateFeedParser()
    parser.feed(response.body.decode("utf-8", errors="replace"))
    return urljoin(response.url, parser.href) if parser.href else None
