import httpx
import pytest

from agentic_core.providers import build_provider
from agentic_core.providers.base import ProviderError, ProviderToolCall
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


def test_openai_compatible_parses_tool_calls():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "tool-1",
                                    "type": "function",
                                    "function": {
                                        "name": "echo",
                                        "arguments": "{ \"value\": 123 }",
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"total_tokens": 16},
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

    response = provider.complete(
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "echo", "description": "", "parameters": {}}}],
        temperature=0.2,
    )

    assert response.message == {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "tool-1",
                "type": "function",
                "function": {"name": "echo", "arguments": "{ \"value\": 123 }"},
            }
        ],
    }
    assert response.tool_calls == [
        ProviderToolCall(
            id="tool-1",
            name="echo",
            arguments={"value": 123},
        )
    ]
    assert response.usage == {"total_tokens": 16}


def test_openai_compatible_requires_message_shape():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"usage": {"total_tokens": 1}},
            )
        )
    )
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

    with pytest.raises(ProviderError, match="provider response missing choices\\[0\\]\\.message"):
        provider.complete(messages=[{"role": "user", "content": "hi"}], tools=[], temperature=0.2)


def test_openai_compatible_requires_dict_response_shape():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=[],
            )
        )
    )
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

    with pytest.raises(ProviderError, match="provider response missing choices\\[0\\]\\.message"):
        provider.complete(messages=[{"role": "user", "content": "hi"}], tools=[], temperature=0.2)


def test_openai_compatible_wraps_http_status_errors():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                503,
                json={"error": {"message": "unavailable"}},
            )
        )
    )
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

    with pytest.raises(ProviderError, match="provider HTTP error"):
        provider.complete(messages=[{"role": "user", "content": "hi"}], tools=[], temperature=0.2)


def test_openai_compatible_wraps_invalid_json_response():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                content=b"{invalid-json",
            )
        )
    )
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

    with pytest.raises(ProviderError, match="provider returned invalid JSON"):
        provider.complete(messages=[{"role": "user", "content": "hi"}], tools=[], temperature=0.2)


def test_openai_compatible_invalid_tool_call_arguments_json():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "tool-1",
                                    "function": {
                                        "name": "broken_tool",
                                        "arguments": "{ invalid json }",
                                    },
                                }
                            ],
                        }
                    }
                ]
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

    with pytest.raises(ProviderError, match="invalid tool call arguments JSON.*broken_tool"):
        provider.complete(messages=[{"role": "user", "content": "hi"}], tools=[], temperature=0.2)


@pytest.mark.parametrize(
    "tool_call",
    [
        {},
        {"function": "not-a-dict"},
    ],
)
def test_openai_compatible_invalid_tool_call_function_shape(tool_call):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [tool_call],
                        }
                    }
                ]
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

    with pytest.raises(ProviderError, match="provider response has invalid tool call"):
        provider.complete(messages=[{"role": "user", "content": "hi"}], tools=[], temperature=0.2)


@pytest.mark.parametrize("name", [None, "", 123])
def test_openai_compatible_invalid_tool_call_name(name):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {"function": {"name": name}},
                            ],
                        }
                    }
                ]
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

    with pytest.raises(ProviderError, match="provider response has invalid tool call"):
        provider.complete(messages=[{"role": "user", "content": "hi"}], tools=[], temperature=0.2)


def test_openai_compatible_close_keeps_injected_client_open():
    client = httpx.Client()
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

    provider.close()

    assert client.is_closed is False
    client.close()
