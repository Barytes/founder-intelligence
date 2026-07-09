import html
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import yaml


def present(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def clean_text(value: Any, *, strip_html: bool, collapse_whitespace: bool) -> str | None:
    if not present(value):
        return None
    text = str(value)
    if strip_html:
        text = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.I)
        text = re.sub(r"</\s*p\s*>", "\n", text, flags=re.I)
        text = re.sub(r"<[^>]*>", " ", text)
        text = html.unescape(text)
    if collapse_whitespace:
        text = re.sub(r"\s+", " ", text)
    return text.strip()


def truncate_text(value: str | None, max_chars: int) -> str | None:
    if not present(value) or int(max_chars) <= 0:
        return value
    return value[:max_chars] if len(value) > max_chars else value


def normalize_datetime(value: Any) -> str | None:
    if not present(value):
        return None
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime

            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    return parsed.isoformat()


def normalize_link(value: Any, remove_params: list[str]) -> str | None:
    if not present(value):
        return None
    text = str(value).strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        return text
    params = [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True) if key not in remove_params]
    query = urlencode(params) if params else ""
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, ""))


def compact_hash(payload: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key, value in payload.items():
        if value is None:
            continue
        if hasattr(value, "__len__") and len(value) == 0:
            continue
        result[key] = value
    return result


def source_map(sources_config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {source["id"]: source for source in sources_config["sources"]}


def content_hash_for(item: dict[str, Any], fields: list[str]) -> str:
    payload = "\n".join(str(item[field]) for field in fields if item.get(field) is not None)
    return hashlib.sha256(payload.encode()).hexdigest()


def source_title_published_at(item: dict[str, Any]) -> str:
    return "|".join(str(value) for value in [item.get("source_id"), item.get("title"), item.get("published_at")] if value is not None)


def build_dedupe_keys(item: dict[str, Any], strategies: list[str]) -> dict[str, str]:
    keys = {}
    for strategy in strategies:
        if strategy == "platform_item_id" and present(item.get("platform_item_id")):
            keys[strategy] = item["platform_item_id"]
        elif strategy == "guid" and present(item.get("guid")):
            keys[strategy] = item["guid"]
        elif strategy == "normalized_link" and present(item.get("normalized_link")):
            keys[strategy] = item["normalized_link"]
        elif strategy == "source_id_title_published_at":
            value = source_title_published_at(item)
            if present(value):
                keys[strategy] = value
        elif strategy == "content_hash" and present(item.get("content_hash")):
            keys[strategy] = item["content_hash"]
        elif strategy == "author_title_content_hash":
            value = "|".join(str(v) for v in [item.get("author"), item.get("title"), item.get("content_hash")] if v is not None)
            if present(value):
                keys[strategy] = value
    return keys


def primary_dedupe_key(dedupe_keys: dict[str, str], strategies: list[str]) -> str | None:
    for strategy in strategies:
        value = dedupe_keys.get(strategy)
        if present(value):
            return f"{strategy}:{value}"
    return None


def canonical_item(raw_item: dict[str, Any], source: dict[str, Any], adapter_result: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    normalization = rules["normalization"]
    strip_html = normalization.get("strip_html") is True
    collapse_whitespace = normalization.get("collapse_whitespace") is True
    remove_params = normalization.get("remove_tracking_params", [])
    title = clean_text(raw_item.get("title"), strip_html=strip_html, collapse_whitespace=collapse_whitespace)
    summary = clean_text(raw_item.get("summary"), strip_html=strip_html, collapse_whitespace=collapse_whitespace)
    content = clean_text(raw_item.get("content"), strip_html=strip_html, collapse_whitespace=collapse_whitespace)
    fetched_at = normalize_datetime(adapter_result.get("fetched_at")) or adapter_result.get("fetched_at")

    item = compact_hash(
        {
            "source_id": adapter_result["source_id"],
            "source_type": adapter_result["source_type"],
            "provider": adapter_result["provider"],
            "source_name": source.get("name"),
            "fetcher": source.get("fetcher"),
            "platform_item_id": raw_item.get("platform_item_id"),
            "guid": raw_item.get("guid"),
            "title": title,
            "link": raw_item.get("link"),
            "normalized_link": normalize_link(raw_item.get("link"), remove_params),
            "published_at": normalize_datetime(raw_item.get("published_at")),
            "fetched_at": fetched_at,
            "author": clean_text(raw_item.get("author"), strip_html=strip_html, collapse_whitespace=collapse_whitespace),
            "summary": truncate_text(summary, normalization.get("max_summary_chars", 0)),
            "content": truncate_text(content, normalization.get("max_content_chars", 0)),
            "category": source.get("category"),
            "tags": source.get("tags"),
            "priority": source.get("priority"),
            "raw": raw_item.get("raw") if normalization.get("preserve_raw_payload") else None,
        }
    )
    hash_fields = rules.get("deduplication", {}).get("content_hash", {}).get("fields") or ["title", "normalized_link", "summary", "content"]
    item["content_hash"] = content_hash_for(item, hash_fields)
    strategies = (
        rules.get("deduplication", {}).get("provider_overrides", {}).get(item.get("provider"))
        or rules.get("deduplication", {}).get("provider_overrides", {}).get(item.get("source_type"))
        or rules.get("deduplication", {}).get("global_strategy")
        or ["platform_item_id", "guid", "normalized_link", "content_hash"]
    )
    item["dedupe_keys"] = build_dedupe_keys(item, strategies)
    item["dedupe_key"] = primary_dedupe_key(item["dedupe_keys"], strategies)
    item["id"] = hashlib.sha256((item.get("dedupe_key") or item["content_hash"]).encode()).hexdigest()
    return item


def quality_flags(item: dict[str, Any], rules: dict[str, Any]) -> list[str]:
    flags = []
    flag_when = rules.get("quality_gates", {}).get("flag_item_when", {})
    if flag_when.get("content_empty") and not present(item.get("content")):
        flags.append("content_empty")
    if flag_when.get("published_at_empty") and not present(item.get("published_at")):
        flags.append("published_at_empty")
    if flag_when.get("author_empty") and not present(item.get("author")):
        flags.append("author_empty")
    return flags


def required_fields_valid(item: dict[str, Any], rules: dict[str, Any]) -> bool:
    return all(present(item.get(field)) for field in rules.get("canonical_item", {}).get("required_fields", []))


def ingest(adapter_output: dict[str, Any], sources_config: dict[str, Any], rules: dict[str, Any], now_iso: str | None = None) -> dict[str, Any]:
    sources = source_map(sources_config)
    seen = {}
    canonical_items = []
    dropped_items = []
    for result in adapter_output["results"]:
        source = sources.get(result["source_id"])
        if not source:
            dropped_items.append({"source_id": result.get("source_id"), "reason": "source_not_found"})
            continue
        for raw_item in result["items"]:
            item = canonical_item(raw_item, source, result, rules)
            item["quality_flags"] = quality_flags(item, rules)
            if rules.get("quality_gates", {}).get("drop_item_when", {}).get("title_empty") is True and not present(item.get("title")):
                dropped_items.append({"raw_id": raw_item.get("raw_id"), "source_id": item.get("source_id"), "reason": "title_empty"})
                continue
            if not required_fields_valid(item, rules):
                dropped_items.append({"raw_id": raw_item.get("raw_id"), "source_id": item.get("source_id"), "reason": "required_fields_missing"})
                continue
            dedupe_key = item.get("dedupe_key")
            if dedupe_key and dedupe_key in seen:
                dropped_items.append({"raw_id": raw_item.get("raw_id"), "source_id": item.get("source_id"), "reason": "duplicate", "duplicate_of": seen[dedupe_key]})
                continue
            if dedupe_key:
                seen[dedupe_key] = item["id"]
            canonical_items.append(item)

    return {
        "run_id": adapter_output.get("run_id"),
        "input_adapter": adapter_output.get("adapter"),
        "contract_version": 1,
        "ingested_at": now_iso or datetime.now().astimezone().isoformat(),
        "summary": {
            "input_results": len(adapter_output["results"]),
            "canonical_items": len(canonical_items),
            "dropped_items": len(dropped_items),
        },
        "items": canonical_items,
        "dropped_items": dropped_items,
    }


def validate_output(output: dict[str, Any], rules: dict[str, Any]) -> None:
    required = rules.get("canonical_item", {}).get("required_fields", [])
    for index, item in enumerate(output["items"]):
        missing = [field for field in required if not present(item.get(field))]
        if missing:
            raise RuntimeError(f"canonical item {index} missing required fields: {', '.join(missing)}")
        if not present(item.get("content_hash")):
            raise RuntimeError(f"canonical item {index} missing content_hash")
        if not present(item.get("dedupe_key")):
            raise RuntimeError(f"canonical item {index} missing dedupe_key")


def run(input_path: Path, sources_path: Path, rules_path: Path, output_path: Path) -> dict[str, Any]:
    adapter_output = json.loads(input_path.read_text(encoding="utf-8"))
    sources_config = yaml.safe_load(sources_path.read_text(encoding="utf-8"))
    rules = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    output = ingest(adapter_output, sources_config, rules)
    validate_output(output, rules)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output
