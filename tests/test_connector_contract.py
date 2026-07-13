from datetime import datetime, timezone
from http.client import IncompleteRead

from fastapi.testclient import TestClient
import pytest

from agentic_core.feature_flags import L4FeatureFlags
from agentic_core.l4.connectors.base import (
    ConnectorCursor,
    ConnectorErrorCode,
    ConnectorLimits,
    ConnectorRegistry,
    HTTPResponseData,
    NetworkPolicyError,
    validate_public_url,
)
from agentic_core.l4.connectors.feed_discovery import (
    discover_alternate_feed,
    validate_discovery_url,
)
from agentic_core.l4.connectors.inbox import (
    InboxConnector,
    InboxService,
    resolve_bilibili_creator_uid,
)
from agentic_core.l4.connectors.rss import RSSConnector, RSSHubConnector
from agentic_core.l4.database import Database
from agentic_core.l4.domain import (
    AcquisitionBinding,
    BindingStatus,
    ConnectorType,
    InboxStatus,
    SourceKind,
    SourceStatus,
    SourceTarget,
)
from agentic_core.l4.hashing import canonical_hash, source_identity_key
from agentic_core.l4.repositories import InboxRepository, SourceRepository
from web_workbench.app import create_app


NOW = datetime(2026, 7, 12, tzinfo=timezone.utc)
PUBLIC = lambda url: url


def binding(
    connector_type=ConnectorType.RSS,
    *,
    url="https://feeds.example.com/rss",
    credential_refs=(),
):
    config = {"connection": {"rss_url": url}}
    if connector_type == ConnectorType.RSSHUB:
        config["connection"]["rsshub_route"] = "/fixture"
    return AcquisitionBinding(
        binding_id=f"binding-{connector_type.value}",
        target_id="target-1",
        connector_type=connector_type,
        config=config,
        config_hash=canonical_hash(config),
        credential_refs=credential_refs,
        status=BindingStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )


class FakeHTTPClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    def get(self, _url, _limits):
        if self.error:
            raise self.error
        return self.response


def feed_response(content_type="application/rss+xml"):
    return HTTPResponseData(
        url="https://feeds.example.com/rss",
        status=200,
        headers={"content-type": content_type},
        body=(
            b"<rss><channel><title>Fixture</title><item><guid>1</guid>"
            b"<title>Agent update</title><link>https://example.com/1</link>"
            b"<description>News</description></item></channel></rss>"
        ),
    )


def test_rss_connector_contract_fetches_and_normalizes_provenance():
    connector = RSSConnector(
        FakeHTTPClient(feed_response()), url_validator=PUBLIC
    )
    source_binding = binding(credential_refs=("RSS_TOKEN",))

    assert connector.discover_capabilities(
        SourceTarget(
            target_id="target-1",
            source_kind=SourceKind.FEED,
            provider="fixture",
            canonical_external_id="feed-1",
            canonical_url="https://feeds.example.com/rss",
            display_name="Fixture",
            identity_key=source_identity_key(
                source_kind="feed",
                provider="fixture",
                canonical_external_id="feed-1",
            ),
        )
    ) == ("rss",)
    assert connector.validate(source_binding).valid is True
    result = connector.fetch(source_binding, ConnectorCursor(), ConnectorLimits())

    assert result.status == "ok"
    assert result.items[0]["title"] == "Agent update"
    assert result.provenance.binding_id == source_binding.binding_id
    assert "RSS_TOKEN" not in result.model_dump_json()


def test_rss_connector_classifies_incomplete_chunked_response_as_source_failure():
    result = RSSConnector(
        FakeHTTPClient(error=IncompleteRead(b"partial")), url_validator=PUBLIC
    ).fetch(binding())

    assert result.status == "failed"
    assert result.errors[0].code == ConnectorErrorCode.HTTP_ERROR
    assert result.errors[0].retryable is True


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (TimeoutError("timed out"), ConnectorErrorCode.TIMEOUT),
        (ValueError("response exceeds max_bytes"), ConnectorErrorCode.OVERSIZE),
        (
            NetworkPolicyError("redirected to private address"),
            ConnectorErrorCode.NETWORK_POLICY,
        ),
    ],
)
def test_rss_connector_classifies_failures(error, expected_code):
    connector = RSSConnector(FakeHTTPClient(error=error), url_validator=PUBLIC)

    result = connector.fetch(binding())

    assert result.status == "failed"
    assert result.errors[0].code == expected_code


def test_rss_connector_rejects_unsupported_content_type():
    connector = RSSConnector(
        FakeHTTPClient(feed_response("text/html")), url_validator=PUBLIC
    )

    result = connector.fetch(binding())

    assert result.errors[0].code == ConnectorErrorCode.UNSUPPORTED_CONTENT_TYPE


def test_network_policy_rejects_literal_and_resolved_private_addresses():
    with pytest.raises(NetworkPolicyError, match="non-public"):
        validate_public_url("http://127.0.0.1/private")

    resolver = lambda *_args: [
        (2, 1, 6, "", ("10.0.0.2", 80)),
    ]
    with pytest.raises(NetworkPolicyError, match="non-public"):
        validate_public_url("https://internal.example/path", resolver=resolver)


def test_rsshub_connector_keeps_platform_target_separate_from_transport():
    connector = RSSHubConnector(
        FakeHTTPClient(feed_response()), url_validator=PUBLIC
    )
    source_binding = binding(ConnectorType.RSSHUB)
    target = SourceTarget(
        target_id="creator-42",
        source_kind=SourceKind.CREATOR,
        provider="bilibili",
        canonical_external_id="42",
        canonical_url="https://space.bilibili.com/42",
        display_name="Creator 42",
        identity_key=source_identity_key(
            source_kind="creator", provider="bilibili", canonical_external_id="42"
        ),
    )

    assert connector.discover_capabilities(target) == ("rsshub",)
    assert source_binding.connector_type == ConnectorType.RSSHUB
    assert target.source_kind == SourceKind.CREATOR


def test_rsshub_connector_allows_only_explicit_trusted_local_instance():
    local = binding(
        ConnectorType.RSSHUB,
        url="http://localhost:1200/bilibili/user/video/42",
    )
    untrusted = binding(
        ConnectorType.RSSHUB,
        url="http://192.168.1.20/internal",
    )
    connector = RSSHubConnector(FakeHTTPClient(feed_response()))

    assert connector.validate(local).valid is True
    assert connector.validate(untrusted).valid is False
    assert untrusted.config["connection"]["rsshub_route"] == "/fixture"


def services(url_validator=PUBLIC, *, bilibili_resolver=None, tracking_probe=None):
    database = Database(":memory:")
    inbox = InboxRepository(database)
    sources = SourceRepository(database)
    return database, InboxService(
        inbox=inbox,
        sources=sources,
        url_validator=url_validator,
        bilibili_resolver=bilibili_resolver or (lambda url: resolve_bilibili_creator_uid(url)),
        tracking_probe=tracking_probe or (lambda _route: True),
        max_content_chars=100,
    ), inbox, sources


def test_inbox_bilibili_creator_creates_target_and_probation_rsshub_binding():
    database, service, inbox, sources = services()

    item = service.submit(
        user_id="user-1",
        inbox_item_id="inbox-1",
        url="https://space.bilibili.com/42",
        title="Creator page",
        note="Follow this creator",
    )
    target = sources.get_target(item.source_target_id)
    bindings = sources.list_bindings(target.target_id)

    assert item.status == InboxStatus.RESOLVED
    assert item.tracking_state == "probation"
    assert item.canonical_item["origin"] == "user_shared"
    assert target.source_kind == SourceKind.CREATOR
    assert target.canonical_external_id == "42"
    assert {binding.connector_type for binding in bindings} == {
        ConnectorType.INBOX,
        ConnectorType.RSSHUB,
    }
    assert next(
        binding for binding in bindings if binding.connector_type == ConnectorType.RSSHUB
    ).status == BindingStatus.ACTIVE
    assert inbox.list_for_user("user-1") == [item]
    database.close()


def test_inbox_bilibili_video_resolves_creator_and_only_claims_tracking_after_probe():
    database, service, _inbox, sources = services(
        bilibili_resolver=lambda _url: "42",
        tracking_probe=lambda _route: True,
    )

    item = service.submit(
        user_id="user-1",
        inbox_item_id="inbox-video",
        url="https://www.bilibili.com/video/BV1fixture",
        title="Video",
    )

    assert item.tracking_state == "probation"
    target = sources.get_target(item.source_target_id)
    assert target.canonical_url == "https://space.bilibili.com/42"
    assert any(
        binding.connector_type == ConnectorType.RSSHUB
        and binding.status == BindingStatus.ACTIVE
        for binding in sources.list_bindings(target.target_id)
    )
    database.close()


def test_inbox_bilibili_probe_failure_is_honestly_unresolved_without_rsshub_binding():
    database, service, _inbox, sources = services(
        bilibili_resolver=lambda _url: "42",
        tracking_probe=lambda _route: False,
    )

    item = service.submit(
        user_id="user-1",
        inbox_item_id="inbox-video",
        url="https://www.bilibili.com/video/BV1fixture",
    )

    assert item.tracking_state == "unresolved"
    assert not any(
        binding.connector_type == ConnectorType.RSSHUB
        for binding in sources.list_bindings(item.source_target_id)
    )
    database.close()


def test_html_alternate_feed_discovery_resolves_relative_feed_url():
    response = HTTPResponseData(
        url="https://example.com/blog/",
        status=200,
        headers={"content-type": "text/html; charset=utf-8"},
        body=(
            b'<html><head><link rel="alternate" type="application/rss+xml" '
            b'href="/feed.xml"></head></html>'
        ),
    )

    assert discover_alternate_feed(
        "https://example.com/blog/", http_client=FakeHTTPClient(response)
    ) == "https://example.com/feed.xml"


def test_discovery_url_allows_proxy_mapped_hostname_but_rejects_literal_and_private_ip():
    proxy_resolver = lambda *_args: [(None, None, None, None, ("198.18.0.42", 0))]
    private_resolver = lambda *_args: [(None, None, None, None, ("192.168.1.5", 0))]

    assert validate_discovery_url(
        "https://example.com/feed", resolver=proxy_resolver
    ) == "https://example.com/feed"
    with pytest.raises(NetworkPolicyError):
        validate_discovery_url("http://198.18.0.42/feed", resolver=proxy_resolver)
    with pytest.raises(NetworkPolicyError):
        validate_discovery_url("https://internal.example/feed", resolver=private_resolver)


def test_wechat_share_remains_honestly_unresolved_but_content_is_saved():
    database, service, inbox, _sources = services()

    item = service.submit(
        user_id="user-1",
        inbox_item_id="inbox-1",
        url="https://mp.weixin.qq.com/s/fixture",
        title="Article",
        captured_content="Captured article text",
    )

    assert item.status == InboxStatus.UNRESOLVED
    assert item.tracking_state == "unresolved"
    assert item.canonical_item["content"] == "Captured article text"
    assert inbox.list_for_user("user-1")[0].canonical_item["origin"] == "user_shared"
    database.close()


def test_inbox_connector_emits_saved_canonical_items_with_cursor():
    database, service, inbox, sources = services()
    item = service.submit(
        user_id="user-1",
        inbox_item_id="inbox-1",
        url="https://example.com/article",
        title="Shared",
    )
    binding_record = next(
        binding
        for binding in sources.list_bindings(item.source_target_id)
        if binding.connector_type == ConnectorType.INBOX
    )

    result = InboxConnector(inbox).fetch(binding_record)

    assert result.status == "ok"
    assert result.items[0]["id"] == item.canonical_item["id"]
    assert result.cursor.value is not None
    database.close()


def test_connector_registry_preserves_partial_success():
    successful = RSSConnector(
        FakeHTTPClient(feed_response()), url_validator=PUBLIC
    )
    failed = RSSConnector(
        FakeHTTPClient(error=TimeoutError("down")), url_validator=PUBLIC
    )
    registry = ConnectorRegistry()
    registry.register("rss", successful)
    first = binding()
    second = binding().model_copy(
        update={"binding_id": "binding-failed", "connector_type": ConnectorType.API}
    )
    registry.register("api", failed)

    results = registry.fetch_all([first, second])

    assert [result.status for result in results] == ["ok", "failed"]


def test_inbox_api_saves_minimal_item_and_rejects_private_or_oversize(tmp_path):
    database, service, _inbox, _sources = services()
    app = create_app(
        repo_root=tmp_path,
        auto_start_rsshub=False,
        l4_database=database,
        inbox_service=service,
        l4_feature_flags=L4FeatureFlags(inbox_enabled=True),
    )
    client = TestClient(app)

    saved = client.post(
        "/api/inbox/items",
        headers={"origin": "http://testserver"},
        json={
            "user_id": "user-1",
            "inbox_item_id": "inbox-1",
            "url": "https://example.com/article",
            "title": "Shared",
        },
    )
    oversize = client.post(
        "/api/inbox/items",
        headers={"origin": "http://testserver"},
        json={"url": "https://example.com/large", "captured_content": "x" * 101},
    )

    assert saved.status_code == 200
    assert saved.json()["item"]["tracking_state"] == "unresolved"
    assert saved.json()["item"]["canonical_item"]["origin"] == "user_shared"
    assert oversize.status_code == 400
    assert len(client.get(
        "/api/inbox/items", params={"user_id": "user-1"}
    ).json()["items"]) == 1
    database.close()


def test_inbox_api_default_network_policy_rejects_private_url(tmp_path):
    database = Database(":memory:")
    app = create_app(
        repo_root=tmp_path,
        auto_start_rsshub=False,
        l4_database=database,
        l4_feature_flags=L4FeatureFlags(inbox_enabled=True),
    )

    response = TestClient(app).post(
        "/api/inbox/items",
        headers={"origin": "http://testserver"},
        json={"url": "http://127.0.0.1/private"},
    )

    assert response.status_code == 400
    assert "not allowed" in response.json()["errors"][0]
    database.close()
