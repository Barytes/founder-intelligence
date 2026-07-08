from typing import Any
import json

import httpx

from agentic_core.providers.base import ProviderResponse, ProviderToolCall
from agentic_core.schemas import ProviderConfig


class OpenAICompatibleProvider:
    def __init__(self, config: ProviderConfig, client: httpx.Client | None = None):
        if not config.api_key:
            raise ValueError(f"missing API key env var: {config.api_key_env}")
        self.config = config
        self.client = client or httpx.Client(timeout=60)

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
        response.raise_for_status()
        data = response.json()
        message = data["choices"][0]["message"]

        tool_calls: list[ProviderToolCall] = []
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            raw_arguments = function.get("arguments") or "{}"
            arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
            tool_calls.append(
                ProviderToolCall(
                    id=call.get("id") or function.get("name") or "tool_call",
                    name=function["name"],
                    arguments=arguments,
                )
            )

        return ProviderResponse(
            message=message,
            tool_calls=tool_calls,
            usage=data.get("usage") or {},
        )
