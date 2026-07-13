from __future__ import annotations

from collections.abc import Mapping
import os

from pydantic import BaseModel, ConfigDict


TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off", ""}


class L4FeatureFlags(BaseModel):
    """Runtime gates for L4 capabilities.

    Direct construction is an explicit all-off compatibility value. Product
    defaults are resolved by ``load_l4_feature_flags`` and are L4-on after M9;
    ``FI_L4_LEGACY_FALLBACK=1`` restores the one-release legacy path.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_enabled: bool = False
    source_catalog_enabled: bool = False
    source_discovery_enabled: bool = False
    agent_ranking_enabled: bool = False
    inbox_enabled: bool = False
    workflow_enabled: bool = False

    @property
    def all_disabled(self) -> bool:
        return not any(self.model_dump().values())


ENV_TO_FIELD = {
    "FI_L4_PROFILE_ENABLED": "profile_enabled",
    "FI_L4_SOURCE_CATALOG_ENABLED": "source_catalog_enabled",
    "FI_L4_SOURCE_DISCOVERY_ENABLED": "source_discovery_enabled",
    "FI_L4_AGENT_RANKING_ENABLED": "agent_ranking_enabled",
    "FI_L4_INBOX_ENABLED": "inbox_enabled",
    "FI_L4_WORKFLOW_ENABLED": "workflow_enabled",
}


def _parse_bool(name: str, value: str | None) -> bool:
    if value is None:
        return False
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ValueError(
        f"{name} must be one of 1/0, true/false, yes/no, or on/off"
    )


def load_l4_feature_flags(
    environ: Mapping[str, str] | None = None,
) -> L4FeatureFlags:
    values = environ if environ is not None else os.environ
    legacy_fallback = _parse_bool(
        "FI_L4_LEGACY_FALLBACK", values.get("FI_L4_LEGACY_FALLBACK")
    )
    product_default = not legacy_fallback
    return L4FeatureFlags(
        **{
            field: (
                product_default
                if values.get(env_name) is None
                else _parse_bool(env_name, values.get(env_name))
            )
            for env_name, field in ENV_TO_FIELD.items()
        }
    )
