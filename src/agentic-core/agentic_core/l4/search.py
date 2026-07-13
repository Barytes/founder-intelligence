from __future__ import annotations

from collections.abc import Sequence
import os
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field


class SearchContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SearchQuery(SearchContract):
    query_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=400)
    reason: str = Field(min_length=1)
    language: str | None = None
    country: str | None = None


class SearchResult(SearchContract):
    result_id: str = Field(min_length=1)
    title: str
    url: str
    description: str = ""
    rank: int = Field(ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(SearchContract):
    provider: str
    query: SearchQuery
    results: tuple[SearchResult, ...]
    request_id: str | None = None
    rate_limit: dict[str, str] = Field(default_factory=dict)


class SearchProviderError(RuntimeError):
    """Sanitized provider failure safe for persisted traces."""


class SearchProvider(Protocol):
    name: str

    def search(self, query: SearchQuery, *, limit: int) -> SearchResponse: ...


class FakeSearchProvider:
    name = "fake"

    def __init__(
        self,
        responses: dict[str, Sequence[SearchResult]] | None = None,
        *,
        error: str | None = None,
    ):
        self.responses = responses or {}
        self.error = error
        self.calls: list[tuple[SearchQuery, int]] = []

    def search(self, query: SearchQuery, *, limit: int) -> SearchResponse:
        self.calls.append((query, limit))
        if self.error:
            raise SearchProviderError(self.error)
        return SearchResponse(
            provider=self.name,
            query=query,
            results=tuple(self.responses.get(query.query_id, ()))[:limit],
        )


class BraveSearchProvider:
    """Minimal Brave Web Search adapter; never receives or records a full profile."""

    name = "brave"
    endpoint = "https://api.search.brave.com/res/v1/web/search"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        timeout_seconds: float = 20,
    ):
        self._api_key = api_key or os.getenv("BRAVE_SEARCH_API_KEY")
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def search(self, query: SearchQuery, *, limit: int = 10) -> SearchResponse:
        if not self._api_key:
            raise SearchProviderError("Brave Search credential is not configured")
        count = max(1, min(limit, 20))
        params: dict[str, str | int] = {"q": query.text, "count": count}
        if query.language:
            params["search_lang"] = query.language
        if query.country:
            params["country"] = query.country
        try:
            response = self._client.get(
                self.endpoint,
                params=params,
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": self._api_key,
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Never include response bodies or request headers: they can contain secrets.
            raise SearchProviderError(
                f"Brave Search request failed ({exc.__class__.__name__})"
            ) from exc

        web_results = payload.get("web", {}).get("results", [])
        normalized: list[SearchResult] = []
        for rank, item in enumerate(web_results[:count], start=1):
            if not isinstance(item, dict) or not isinstance(item.get("url"), str):
                continue
            normalized.append(
                SearchResult(
                    result_id=f"{query.query_id}:{rank}",
                    title=str(item.get("title") or ""),
                    url=item["url"],
                    description=str(item.get("description") or ""),
                    rank=rank,
                    metadata={
                        "language": item.get("language"),
                        "family_friendly": item.get("family_friendly"),
                    },
                )
            )
        safe_rate_headers = {
            key.lower(): value
            for key, value in response.headers.items()
            if key.lower().startswith("x-ratelimit")
        }
        return SearchResponse(
            provider=self.name,
            query=query,
            results=tuple(normalized),
            request_id=response.headers.get("x-request-id"),
            rate_limit=safe_rate_headers,
        )
