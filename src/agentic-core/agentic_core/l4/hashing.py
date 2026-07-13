from __future__ import annotations

from hashlib import sha256
import json
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel

from agentic_core.l4.domain import SourceKind


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def profile_snapshot_hash(snapshot: Any) -> str:
    if isinstance(snapshot, BaseModel):
        payload = snapshot.model_dump(
            mode="json",
            exclude={"profile_hash", "profile_id", "created_at"},
        )
    else:
        payload = dict(snapshot)
        for key in ("profile_hash", "profile_id", "created_at"):
            payload.pop(key, None)
    return canonical_hash(payload)


def normalize_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if scheme not in {"http", "https"} or not host:
        raise ValueError("source URL must be absolute HTTP(S)")
    port = parsed.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunsplit((scheme, host, path, query, ""))


def source_identity_key(
    *,
    source_kind: SourceKind | str,
    provider: str,
    canonical_external_id: str | None = None,
    canonical_url: str | None = None,
) -> str:
    kind = SourceKind(source_kind).value
    normalized_provider = provider.strip().lower()
    if canonical_external_id:
        material = f"v1:external:{kind}:{normalized_provider}:{canonical_external_id.strip()}"
    elif canonical_url:
        material = f"v1:url:{kind}:{normalized_provider}:{normalize_url(canonical_url)}"
    else:
        raise ValueError("source identity requires external id or URL")
    return sha256(material.encode("utf-8")).hexdigest()


def idempotency_key(namespace: str, value: Any) -> str:
    return f"{namespace}:v1:{canonical_hash(value)}"
