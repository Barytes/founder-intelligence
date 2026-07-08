from agentic_core.providers.base import Provider
from agentic_core.providers.openai_compatible import OpenAICompatibleProvider
from agentic_core.schemas import ProviderConfig


def build_provider(config: ProviderConfig, timeout_seconds: float = 60) -> Provider:
    if config.type == "openai_compatible":
        return OpenAICompatibleProvider(config, timeout_seconds=timeout_seconds)
    raise ValueError(f"unsupported provider type: {config.type}")
