from agentic_core.providers.base import Provider
from agentic_core.providers.openai_compatible import OpenAICompatibleProvider
from agentic_core.schemas import ProviderConfig


def build_provider(config: ProviderConfig) -> Provider:
    if config.type == "openai_compatible":
        return OpenAICompatibleProvider(config)
    raise ValueError(f"unsupported provider type: {config.type}")
