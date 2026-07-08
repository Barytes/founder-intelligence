import httpx
import pytest

from agentic_core.providers import build_provider
from agentic_core.providers.openai_compatible import OpenAICompatibleProvider
from agentic_core.schemas import ProviderConfig


def test_provider_factory_builds_openai_compatible_provider():
    provider = build_provider(
        ProviderConfig(
            type="openai_compatible",
            api_key_env="TEST_KEY",
            api_key="secret",
            base_url="https://example.test/v1",
            model="test-model",
        )
    )

    assert isinstance(provider, OpenAICompatibleProvider)


def test_openai_compatible_requires_api_key():
    config = ProviderConfig(
        type="openai_compatible",
        api_key_env="TEST_KEY",
        api_key=None,
        base_url="https://example.test/v1",
        model="test-model",
    )

    with pytest.raises(ValueError, match="missing API key"):
        OpenAICompatibleProvider(config)


def test_openai_compatible_parses_final_text_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://example.test/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "hello"}}
                ],
                "usage": {"total_tokens": 7},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        ProviderConfig(
            type="openai_compatible",
            api_key_env="TEST_KEY",
            api_key="secret",
            base_url="https://example.test/v1",
            model="test-model",
        ),
        client=client,
    )

    response = provider.complete(messages=[{"role": "user", "content": "hi"}], tools=[], temperature=0.1)

    assert response.message == {"role": "assistant", "content": "hello"}
    assert response.tool_calls == []
    assert response.usage == {"total_tokens": 7}
