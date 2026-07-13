import pytest
from fastapi.testclient import TestClient

from agentic_core.feature_flags import L4FeatureFlags, load_l4_feature_flags
from web_workbench.app import create_app


L4_ENV_NAMES = (
    "FI_L4_PROFILE_ENABLED",
    "FI_L4_SOURCE_CATALOG_ENABLED",
    "FI_L4_SOURCE_DISCOVERY_ENABLED",
    "FI_L4_AGENT_RANKING_ENABLED",
    "FI_L4_INBOX_ENABLED",
    "FI_L4_WORKFLOW_ENABLED",
)


def test_legacy_fallback_explicitly_disables_all_l4_flags(monkeypatch):
    for name in L4_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FI_L4_LEGACY_FALLBACK", "1")

    flags = load_l4_feature_flags()

    assert flags == L4FeatureFlags()
    assert flags.all_disabled is True


def test_product_default_enables_l4_without_legacy_fallback():
    flags = load_l4_feature_flags({})

    assert flags.model_dump() == {
        "profile_enabled": True,
        "source_catalog_enabled": True,
        "source_discovery_enabled": True,
        "agent_ranking_enabled": True,
        "inbox_enabled": True,
        "workflow_enabled": True,
    }


def test_l4_feature_flags_parse_explicit_values():
    flags = load_l4_feature_flags(
        {
            "FI_L4_PROFILE_ENABLED": "true",
            "FI_L4_SOURCE_CATALOG_ENABLED": "1",
            "FI_L4_SOURCE_DISCOVERY_ENABLED": "yes",
            "FI_L4_AGENT_RANKING_ENABLED": "on",
            "FI_L4_INBOX_ENABLED": "0",
            "FI_L4_WORKFLOW_ENABLED": "true",
        }
    )

    assert flags.model_dump() == {
        "profile_enabled": True,
        "source_catalog_enabled": True,
        "source_discovery_enabled": True,
        "agent_ranking_enabled": True,
        "inbox_enabled": False,
        "workflow_enabled": True,
    }
    assert flags.all_disabled is False


def test_l4_feature_flags_reject_unknown_boolean_value():
    with pytest.raises(ValueError, match="FI_L4_PROFILE_ENABLED"):
        load_l4_feature_flags({"FI_L4_PROFILE_ENABLED": "maybe"})


def test_default_config_exposes_disabled_l4_gates(tmp_path):
    client = TestClient(
        create_app(
            repo_root=tmp_path,
            auto_start_rsshub=False,
            l4_feature_flags=L4FeatureFlags(),
        )
    )

    response = client.get("/api/default-config")

    assert response.status_code == 200
    assert response.json()["l4_feature_flags"] == {
        "profile_enabled": False,
        "source_catalog_enabled": False,
        "source_discovery_enabled": False,
        "agent_ranking_enabled": False,
        "inbox_enabled": False,
        "workflow_enabled": False,
    }
