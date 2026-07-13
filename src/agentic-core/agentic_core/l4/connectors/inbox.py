from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx

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
from agentic_core.l4.connectors.rss import RSSHubConnector
from agentic_core.l4.domain import (
    AcquisitionBinding,
    BindingStatus,
    ConnectorType,
    InboxItem,
    InboxStatus,
    SourceKind,
    SourceStatus,
    SourceTarget,
)
from agentic_core.l4.hashing import canonical_hash, normalize_url, source_identity_key
from agentic_core.l4.repositories import InboxRepository, SourceRepository


BILIBILI_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 founder-intelligence/1",
    "Referer": "https://www.bilibili.com/",
}
BILIBILI_HOSTS = {
    "space.bilibili.com",
    "bilibili.com",
    "www.bilibili.com",
    "m.bilibili.com",
    "b23.tv",
}


def validate_inbox_url(url: str) -> str:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower()
    if hostname in BILIBILI_HOSTS:
        if parsed.scheme != "https":
            raise NetworkPolicyError("Bilibili URL must use HTTPS")
        return url
    return validate_public_url(url)


def resolve_bilibili_creator_uid(
    url: str,
    *,
    http_client: HTTPClient | None = None,
) -> str | None:
    """Resolve a Bilibili creator or video URL to the creator's numeric UID."""

    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower()
    direct = re.fullmatch(r"/([0-9]+)/?", parsed.path)
    if hostname == "space.bilibili.com" and direct:
        return direct.group(1)
    if hostname == "b23.tv":
        if http_client is not None:
            response = http_client.get(
                url,
                ConnectorLimits(max_bytes=100_000, max_items=1, max_redirects=3),
            )
            final_url = response.url
        else:
            response = httpx.get(
                url,
                follow_redirects=True,
                timeout=10,
                headers=BILIBILI_HTTP_HEADERS,
            )
            response.raise_for_status()
            final_url = str(response.url)
        final_host = (urlsplit(final_url).hostname or "").lower()
        if final_host not in {"bilibili.com", "www.bilibili.com", "m.bilibili.com"}:
            return None
        return resolve_bilibili_creator_uid(final_url, http_client=http_client)
    if hostname not in {"bilibili.com", "www.bilibili.com", "m.bilibili.com"}:
        return None
    video = re.match(r"^/video/(BV[0-9A-Za-z]+)", parsed.path, re.IGNORECASE)
    if not video:
        return None
    api_url = (
        "https://api.bilibili.com/x/web-interface/view?bvid="
        f"{quote(video.group(1))}"
    )
    if http_client is not None:
        response = http_client.get(
            api_url,
            ConnectorLimits(max_bytes=500_000, max_items=1, max_redirects=1),
        )
        body = response.body
    else:
        # The endpoint and query shape are fixed and do not contain a user-selected
        # host.  A dedicated allowlisted request avoids weakening the generic SSRF
        # policy in proxy environments that map public DNS to 198.18.0.0/15.
        response = httpx.get(api_url, timeout=10, headers=BILIBILI_HTTP_HEADERS)
        response.raise_for_status()
        body = response.content
        if len(body) > 500_000:
            raise ValueError("Bilibili metadata response exceeds max_bytes")
    payload = json.loads(body.decode("utf-8"))
    owner = payload.get("data", {}).get("owner", {}) if payload.get("code") == 0 else {}
    uid = owner.get("mid")
    return str(uid) if isinstance(uid, int | str) and str(uid).isdigit() else None


def probe_bilibili_rsshub_route(
    route: str,
    *,
    http_client: HTTPClient | None = None,
) -> bool:
    config = {
        "connection": {
            "rsshub_route": route,
            "rss_url": f"http://localhost:1200{route}",
        }
    }
    binding = AcquisitionBinding(
        binding_id="binding-bilibili-probe",
        target_id="target-bilibili-probe",
        connector_type=ConnectorType.RSSHUB,
        config=config,
        config_hash=canonical_hash(config),
        status=BindingStatus.ACTIVE,
    )
    return RSSHubConnector(http_client).fetch(
        binding,
        limits=ConnectorLimits(max_items=1, max_bytes=1_000_000),
    ).status == "ok"


class InboxService:
    def __init__(
        self,
        *,
        inbox: InboxRepository,
        sources: SourceRepository,
        url_validator: Callable[[str], str] = validate_inbox_url,
        bilibili_resolver: Callable[[str], str | None] = resolve_bilibili_creator_uid,
        tracking_probe: Callable[[str], bool] = probe_bilibili_rsshub_route,
        max_content_chars: int = 200_000,
    ):
        self.inbox = inbox
        self.sources = sources
        self.url_validator = url_validator
        self.bilibili_resolver = bilibili_resolver
        self.tracking_probe = tracking_probe
        self.max_content_chars = max_content_chars

    def submit(
        self,
        *,
        user_id: str,
        url: str,
        title: str | None = None,
        note: str | None = None,
        captured_content: str | None = None,
        inbox_item_id: str | None = None,
    ) -> InboxItem:
        normalized_url = normalize_url(url)
        self.url_validator(normalized_url)
        if captured_content and len(captured_content) > self.max_content_chars:
            raise ValueError("captured content exceeds limit")
        parsed = urlsplit(normalized_url)
        item_id = inbox_item_id or f"inbox-{uuid4()}"
        target, tracking_state = self._resolve_target(parsed.hostname or "", normalized_url)
        saved_target = self.sources.upsert_target(target, reason=f"inbox:{item_id}")
        binding_config = {"user_id": user_id, "inbox_item_id": item_id}
        binding = AcquisitionBinding(
            binding_id=f"binding-inbox-{canonical_hash(binding_config)[:20]}",
            target_id=saved_target.target_id,
            connector_type=ConnectorType.INBOX,
            config=binding_config,
            config_hash=canonical_hash(binding_config),
            status=BindingStatus.ACTIVE,
        )
        self.sources.add_binding(binding, reason=f"inbox:{item_id}")
        if tracking_state == "probation":
            route = saved_target.metadata.get("suggested_route")
            rsshub_config = {
                "connection": {
                    "rsshub_route": route,
                    "rss_url": f"http://localhost:1200{route}",
                },
                "probation_quota": 10,
            }
            self.sources.add_binding(
                AcquisitionBinding(
                    binding_id=f"binding-rsshub-{canonical_hash([saved_target.target_id, route])[:20]}",
                    target_id=saved_target.target_id,
                    connector_type=ConnectorType.RSSHUB,
                    config=rsshub_config,
                    config_hash=canonical_hash(rsshub_config),
                    status=BindingStatus.ACTIVE,
                ),
                reason=f"inbox_resolution:{item_id}",
            )
        content = captured_content or note or ""
        content_hash = sha256(
            f"{normalized_url}\n{title or ''}\n{content}".encode("utf-8")
        ).hexdigest()
        canonical_item = {
            "id": sha256(f"inbox:{item_id}".encode()).hexdigest(),
            "source_id": saved_target.target_id,
            "source_type": "inbox",
            "provider": parsed.hostname or "inbox",
            "source_name": saved_target.display_name,
            "title": title or normalized_url,
            "link": normalized_url,
            "normalized_link": normalized_url,
            "summary": note or captured_content or "",
            "content": captured_content or note or "",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "content_hash": content_hash,
            "dedupe_key": f"normalized_link:{normalized_url}",
            "origin": "user_shared",
            "tags": ["user-shared"],
            "category": "inbox",
            "priority": "high",
        }
        item = InboxItem(
            inbox_item_id=item_id,
            user_id=user_id,
            url=normalized_url,
            title=title,
            note=note,
            captured_content=captured_content,
            status=(
                InboxStatus.RESOLVED
                if tracking_state == "probation"
                else InboxStatus.UNRESOLVED
            ),
            source_target_id=saved_target.target_id,
            tracking_state=tracking_state,
            canonical_item=canonical_item,
        )
        return self.inbox.append(item)

    def _resolve_target(self, hostname: str, url: str) -> tuple[SourceTarget, str]:
        normalized_host = hostname.lower()
        uid: str | None = None
        if normalized_host in BILIBILI_HOSTS:
            try:
                uid = self.bilibili_resolver(url)
            except Exception:
                uid = None
        if uid:
            route = f"/bilibili/user/video/{uid}"
            try:
                tracking_ready = self.tracking_probe(route)
            except Exception:
                tracking_ready = False
            identity = source_identity_key(
                source_kind=SourceKind.CREATOR,
                provider="bilibili",
                canonical_external_id=uid,
            )
            return (
                SourceTarget(
                    target_id=f"target-{identity[:20]}",
                    source_kind=SourceKind.CREATOR,
                    provider="bilibili",
                    canonical_external_id=uid,
                    canonical_url=f"https://space.bilibili.com/{uid}",
                    display_name=f"Bilibili creator {uid}",
                    identity_key=identity,
                    status=(
                        SourceStatus.PROBATION
                        if tracking_ready
                        else SourceStatus.CANDIDATE
                    ),
                    metadata={
                        "suggested_connector": "rsshub",
                        "suggested_route": route,
                        "tracking_probe": "passed" if tracking_ready else "failed",
                    },
                ),
                "probation" if tracking_ready else "unresolved",
            )
        kind = (
            SourceKind.PUBLICATION
            if hostname == "mp.weixin.qq.com"
            else SourceKind.WEBSITE
        )
        identity = source_identity_key(
            source_kind=kind,
            provider=hostname or "web",
            canonical_url=url,
        )
        return (
            SourceTarget(
                target_id=f"target-{identity[:20]}",
                source_kind=kind,
                provider=hostname or "web",
                canonical_url=url,
                display_name=hostname or url,
                identity_key=identity,
                status=SourceStatus.CANDIDATE,
                metadata={"origin": "user_shared"},
            ),
            "unresolved",
        )


class InboxConnector:
    connector_type = ConnectorType.INBOX

    def __init__(self, repository: InboxRepository):
        self.repository = repository

    def discover_capabilities(self, _target: SourceTarget) -> tuple[str, ...]:
        return ("inbox",)

    def validate(self, binding: AcquisitionBinding) -> ConnectorValidation:
        user_id = binding.config.get("user_id")
        if not user_id:
            return ConnectorValidation(
                valid=False,
                errors=(
                    ConnectorError(
                        code=ConnectorErrorCode.INVALID_CONFIG,
                        message="Inbox binding requires user_id",
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
            connector_type=ConnectorType.INBOX.value,
            metadata={
                "origin": "user_shared",
                **{key: value for key, value in metadata.items() if "credential" not in key},
            },
        )

    def fetch(
        self,
        binding: AcquisitionBinding,
        cursor: ConnectorCursor = ConnectorCursor(),
        limits: ConnectorLimits = ConnectorLimits(),
    ) -> ConnectorResult:
        validation = self.validate(binding)
        if not validation.valid:
            return ConnectorResult(
                status="failed",
                errors=validation.errors,
                provenance=self.normalize_provenance(binding),
            )
        items = self.repository.list_for_user(str(binding.config["user_id"]))
        if cursor.value:
            items = [item for item in items if item.created_at.isoformat() > cursor.value]
        selected = items[: limits.max_items]
        return ConnectorResult(
            status="ok",
            items=tuple(item.canonical_item for item in selected),
            cursor=ConnectorCursor(
                value=selected[-1].created_at.isoformat() if selected else cursor.value
            ),
            provenance=self.normalize_provenance(binding),
        )

    def health(self, binding: AcquisitionBinding) -> ConnectorHealth:
        validation = self.validate(binding)
        return ConnectorHealth(
            status="healthy" if validation.valid else "invalid",
            checked_at=datetime.now(timezone.utc).isoformat(),
            errors=validation.errors,
        )
