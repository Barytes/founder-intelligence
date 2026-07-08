import json
from typing import Any

import httpx

from agentic_core.providers.base import ProviderResponse, ProviderToolCall, ProviderError
from agentic_core.schemas import ProviderConfig


class OpenAICompatibleProvider:
    def __init__(self, config: ProviderConfig, client: httpx.Client | None = None):
        if not config.api_key:
            raise ValueError(f"missing API key env var: {config.api_key_env}")
        self.config = config
        self.client = client or httpx.Client(timeout=60)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float,
    ) -> ProviderResponse:
        base_url = (self.config.base_url or self.config.default_base_url).rstrip("/")
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        response = self.client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"provider HTTP error: {exc.response.status_code}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError("provider returned invalid JSON") from exc

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderError("provider response missing choices[0].message")
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise ProviderError("provider response missing choices[0].message")
        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise ProviderError("provider response missing choices[0].message")

        tool_calls: list[ProviderToolCall] = []
        raw_tool_calls = message.get("tool_calls")
        if raw_tool_calls is None:
            raw_tool_calls = []
        elif not isinstance(raw_tool_calls, list):
            raise ProviderError("provider response has invalid tool call")

        for call in raw_tool_calls:
            if not isinstance(call, dict):
                raise ProviderError("provider response has invalid tool call")
            function = call.get("function")
            if not isinstance(function, dict):
                raise ProviderError("provider response has invalid tool call")
            function_name = function.get("name")
            if not isinstance(function_name, str) or not function_name:
                raise ProviderError("provider response has invalid tool call")
            raw_arguments = function.get("arguments") or "{}"
            try:
                arguments = (
                    json.loads(raw_arguments)
                    if isinstance(raw_arguments, str)
                    else raw_arguments
                )
                if not isinstance(arguments, dict):
                    raise TypeError
            except (TypeError, json.JSONDecodeError) as exc:
                raise ProviderError(
                    f"invalid tool call arguments JSON for tool {function_name}"
                ) from exc
            tool_calls.append(
                ProviderToolCall(
                    id=call.get("id") or function_name or "tool_call",
                    name=function_name,
                    arguments=arguments,
                )
            )

        return ProviderResponse(
            message=message,
            tool_calls=tool_calls,
            usage=data.get("usage") or {},
        )
