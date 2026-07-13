from __future__ import annotations

from datetime import datetime, timezone
from http.client import HTTPException
from typing import Any
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from xml.etree import ElementTree

from agentic_core.l4.connectors.base import (
    ConnectorCursor,
    ConnectorError,
    ConnectorErrorCode,
    ConnectorHealth,
    ConnectorLimits,
    ConnectorProvenance,
    ConnectorResult,
    ConnectorValidation,
    HTTPClient,
    NetworkPolicyError,
    UrllibHTTPClient,
    validate_public_url,
)
from agentic_core.l4.domain import AcquisitionBinding, ConnectorType, SourceTarget
from agentic_core.pipeline.fetch_rss import parse_feed


class RSSConnector:
    connector_type = ConnectorType.RSS

    def __init__(
        self,
        http_client: HTTPClient | None = None,
        *,
        url_validator=validate_public_url,
    ):
        self.http_client = http_client or UrllibHTTPClient()
        self.url_validator = url_validator

    def discover_capabilities(self, target: SourceTarget) -> tuple[str, ...]:
        return ("rss",) if target.canonical_url else ()

    def _url(self, binding: AcquisitionBinding) -> str | None:
        connection = binding.config.get("connection") or {}
        return connection.get("rss_url") or binding.config.get("rss_url")

    def validate(self, binding: AcquisitionBinding) -> ConnectorValidation:
        url = self._url(binding)
        if not url:
            return ConnectorValidation(
                valid=False,
                errors=(
                    ConnectorError(
                        code=ConnectorErrorCode.INVALID_CONFIG,
                        message="RSS binding requires rss_url",
                    ),
                ),
            )
        try:
            self.url_validator(str(url))
        except NetworkPolicyError as exc:
            return ConnectorValidation(
                valid=False,
                errors=(
                    ConnectorError(
                        code=ConnectorErrorCode.NETWORK_POLICY,
                        message=str(exc),
                    ),
                ),
            )
        return ConnectorValidation(valid=True)

    def normalize_provenance(
        self, binding: AcquisitionBinding, **metadata: Any
    ) -> ConnectorProvenance:
        return ConnectorProvenance(
            target_id=binding.target_id,
            binding_id=binding.binding_id,
            connector_type=binding.connector_type.value,
            requested_url=self._url(binding),
            final_url=metadata.get("final_url"),
            metadata={
                key: value
                for key, value in metadata.items()
                if key != "final_url" and "credential" not in key.lower()
            },
        )

    def fetch(
        self,
        binding: AcquisitionBinding,
        cursor: ConnectorCursor = ConnectorCursor(),
        limits: ConnectorLimits = ConnectorLimits(),
    ) -> ConnectorResult:
        validation = self.validate(binding)
        provenance = self.normalize_provenance(binding)
        if not validation.valid:
            return ConnectorResult(
                status="failed", errors=validation.errors, provenance=provenance
            )
        url = str(self._url(binding))
        try:
            response = self.http_client.get(url, limits)
            content_type = response.headers.get("content-type", "").lower()
            if content_type and not any(
                allowed in content_type
                for allowed in ("xml", "rss", "atom", "text/plain")
            ):
                return ConnectorResult(
                    status="failed",
                    errors=(
                        ConnectorError(
                            code=ConnectorErrorCode.UNSUPPORTED_CONTENT_TYPE,
                            message=f"unsupported content type: {content_type}",
                        ),
                    ),
                    provenance=self.normalize_provenance(
                        binding, final_url=response.url
                    ),
                )
            items, metadata = parse_feed(
                response.body.decode("utf-8"),
                binding.binding_id,
                limits.max_items,
            )
            return ConnectorResult(
                status="ok",
                items=tuple(items),
                cursor=ConnectorCursor(
                    value=datetime.now(timezone.utc).isoformat()
                ),
                provenance=self.normalize_provenance(
                    binding, final_url=response.url, feed=metadata
                ),
                rate_limit={
                    key: response.headers[key]
                    for key in ("x-ratelimit-limit", "x-ratelimit-remaining", "retry-after")
                    if key in response.headers
                },
            )
        except NetworkPolicyError as exc:
            error = ConnectorError(
                code=ConnectorErrorCode.NETWORK_POLICY, message=str(exc)
            )
        except TimeoutError as exc:
            error = ConnectorError(
                code=ConnectorErrorCode.TIMEOUT, message=str(exc), retryable=True
            )
        except ValueError as exc:
            code = (
                ConnectorErrorCode.OVERSIZE
                if "max_bytes" in str(exc)
                else ConnectorErrorCode.PARSE_ERROR
            )
            error = ConnectorError(code=code, message=str(exc))
        except (ElementTree.ParseError, UnicodeDecodeError) as exc:
            error = ConnectorError(
                code=ConnectorErrorCode.PARSE_ERROR, message=str(exc)
            )
        except (HTTPError, URLError, HTTPException, OSError) as exc:
            error = ConnectorError(
                code=ConnectorErrorCode.HTTP_ERROR,
                message=str(exc),
                retryable=True,
            )
        return ConnectorResult(
            status="failed", errors=(error,), provenance=provenance
        )

    def health(self, binding: AcquisitionBinding) -> ConnectorHealth:
        validation = self.validate(binding)
        return ConnectorHealth(
            status="healthy" if validation.valid else "invalid",
            checked_at=datetime.now(timezone.utc).isoformat(),
            errors=validation.errors,
        )


class RSSHubConnector(RSSConnector):
    connector_type = ConnectorType.RSSHUB

    def __init__(
        self,
        http_client: HTTPClient | None = None,
        *,
        allowed_instances: tuple[str, ...] = (
            "http://localhost:1200",
            "http://127.0.0.1:1200",
        ),
        url_validator=None,
    ):
        allowed = {instance.rstrip("/") for instance in allowed_instances}

        def validate_rsshub_url(url: str) -> str:
            parsed = urlsplit(url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            if origin in allowed:
                return url
            return (url_validator or validate_public_url)(url)

        super().__init__(
            http_client or UrllibHTTPClient(url_validator=validate_rsshub_url),
            url_validator=validate_rsshub_url,
        )

    def discover_capabilities(self, target: SourceTarget) -> tuple[str, ...]:
        if target.provider in {"bilibili", "github", "zhihu"}:
            return ("rsshub",)
        return ()

    def validate(self, binding: AcquisitionBinding) -> ConnectorValidation:
        connection = binding.config.get("connection") or {}
        if not connection.get("rsshub_route") and not connection.get("rss_url"):
            return ConnectorValidation(
                valid=False,
                errors=(
                    ConnectorError(
                        code=ConnectorErrorCode.INVALID_CONFIG,
                        message="RSSHub binding requires route or rss_url",
                    ),
                ),
            )
        return super().validate(binding)
