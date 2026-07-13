from __future__ import annotations

from enum import Enum
import ipaddress
import socket
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import BaseModel, ConfigDict, Field

from agentic_core.l4.domain import AcquisitionBinding, SourceTarget


class ConnectorContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ConnectorErrorCode(str, Enum):
    INVALID_CONFIG = "invalid_config"
    NETWORK_POLICY = "network_policy"
    TIMEOUT = "timeout"
    OVERSIZE = "oversize"
    UNSUPPORTED_CONTENT_TYPE = "unsupported_content_type"
    HTTP_ERROR = "http_error"
    PARSE_ERROR = "parse_error"
    CREDENTIAL_MISSING = "credential_missing"


class ConnectorError(ConnectorContract):
    code: ConnectorErrorCode
    message: str
    retryable: bool = False


class ConnectorLimits(ConnectorContract):
    timeout_seconds: float = Field(default=20, gt=0, le=120)
    max_bytes: int = Field(default=2_000_000, ge=1, le=20_000_000)
    max_items: int = Field(default=50, ge=1, le=500)
    max_redirects: int = Field(default=3, ge=0, le=10)


class ConnectorCursor(ConnectorContract):
    value: str | None = None


class ConnectorProvenance(ConnectorContract):
    target_id: str
    binding_id: str
    connector_type: str
    requested_url: str | None = None
    final_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConnectorResult(ConnectorContract):
    status: str
    items: tuple[dict[str, Any], ...] = ()
    errors: tuple[ConnectorError, ...] = ()
    cursor: ConnectorCursor = ConnectorCursor()
    provenance: ConnectorProvenance
    rate_limit: dict[str, Any] = Field(default_factory=dict)


class ConnectorValidation(ConnectorContract):
    valid: bool
    errors: tuple[ConnectorError, ...] = ()


class ConnectorHealth(ConnectorContract):
    status: str
    checked_at: str
    errors: tuple[ConnectorError, ...] = ()


class Connector(Protocol):
    def discover_capabilities(self, target: SourceTarget) -> tuple[str, ...]: ...
    def validate(self, binding: AcquisitionBinding) -> ConnectorValidation: ...
    def fetch(
        self,
        binding: AcquisitionBinding,
        cursor: ConnectorCursor,
        limits: ConnectorLimits,
    ) -> ConnectorResult: ...
    def health(self, binding: AcquisitionBinding) -> ConnectorHealth: ...
    def normalize_provenance(
        self, binding: AcquisitionBinding, **metadata: Any
    ) -> ConnectorProvenance: ...


class NetworkPolicyError(ValueError):
    pass


def validate_public_url(url: str, *, resolver=socket.getaddrinfo) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise NetworkPolicyError("URL must be absolute HTTP(S)")
    hostname = parsed.hostname.lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise NetworkPolicyError("localhost is not allowed")
    try:
        literal = ipaddress.ip_address(hostname)
        addresses = [literal]
    except ValueError:
        try:
            addresses = {
                ipaddress.ip_address(row[4][0])
                for row in resolver(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
            }
        except OSError as exc:
            raise NetworkPolicyError(f"hostname resolution failed: {hostname}") from exc
    for address in addresses:
        if not address.is_global:
            raise NetworkPolicyError(f"non-public address is not allowed: {address}")
    return url


class HTTPResponseData(ConnectorContract):
    url: str
    status: int
    headers: dict[str, str]
    body: bytes


class HTTPClient(Protocol):
    def get(self, url: str, limits: ConnectorLimits) -> HTTPResponseData: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


class UrllibHTTPClient:
    def __init__(
        self,
        *,
        resolver=socket.getaddrinfo,
        url_validator=None,
    ):
        self.resolver = resolver
        self.url_validator = url_validator
        self.opener = build_opener(_NoRedirect)

    def get(self, url: str, limits: ConnectorLimits) -> HTTPResponseData:
        current = url
        for redirect_count in range(limits.max_redirects + 1):
            if self.url_validator is not None:
                self.url_validator(current)
            else:
                validate_public_url(current, resolver=self.resolver)
            request = Request(current, headers={"User-Agent": "founder-intelligence/1"})
            try:
                response = self.opener.open(request, timeout=limits.timeout_seconds)
            except HTTPError as exc:
                if 300 <= exc.code < 400 and exc.headers.get("Location"):
                    if redirect_count >= limits.max_redirects:
                        raise NetworkPolicyError("redirect limit exceeded") from exc
                    current = urljoin(current, exc.headers["Location"])
                    continue
                raise
            length = response.headers.get("Content-Length")
            if length and int(length) > limits.max_bytes:
                response.close()
                raise ValueError("response exceeds max_bytes")
            body = response.read(limits.max_bytes + 1)
            final_url = response.geturl()
            response.close()
            if len(body) > limits.max_bytes:
                raise ValueError("response exceeds max_bytes")
            return HTTPResponseData(
                url=final_url,
                status=int(response.status),
                headers={key.lower(): value for key, value in response.headers.items()},
                body=body,
            )
        raise NetworkPolicyError("redirect limit exceeded")


class ConnectorRegistry:
    def __init__(self):
        self._connectors: dict[str, Connector] = {}

    def register(self, connector_type: str, connector: Connector) -> None:
        self._connectors[connector_type] = connector

    def get(self, connector_type: str) -> Connector:
        try:
            return self._connectors[connector_type]
        except KeyError as exc:
            raise KeyError(f"connector is not registered: {connector_type}") from exc

    def fetch_all(
        self,
        bindings: list[AcquisitionBinding],
        *,
        limits: ConnectorLimits = ConnectorLimits(),
    ) -> tuple[ConnectorResult, ...]:
        results = []
        for binding in bindings:
            try:
                connector = self.get(binding.connector_type.value)
                results.append(
                    connector.fetch(binding, ConnectorCursor(), limits)
                )
            except Exception as exc:
                results.append(
                    ConnectorResult(
                        status="failed",
                        errors=(
                            ConnectorError(
                                code=ConnectorErrorCode.HTTP_ERROR,
                                message=str(exc),
                                retryable=True,
                            ),
                        ),
                        provenance=ConnectorProvenance(
                            target_id=binding.target_id,
                            binding_id=binding.binding_id,
                            connector_type=binding.connector_type.value,
                        ),
                    )
                )
        return tuple(results)
