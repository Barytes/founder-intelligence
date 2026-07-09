import hashlib
import re
import secrets
from datetime import datetime
from typing import Any
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET


def present(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def clean_text(value: Any) -> str | None:
    if not present(value):
        return None
    return re.sub(r"\s+", " ", str(value)).strip()


def local_name(tag: str) -> str:
    return tag.split("}", 1)[-1].split(":", 1)[-1]


def child_text(element: ET.Element, *names: str) -> str | None:
    candidates = set(names)
    for child in list(element):
        if local_name(child.tag) in candidates or child.tag in candidates:
            return clean_text("".join(child.itertext()))
    return None


def child_values(element: ET.Element, *names: str) -> list[str]:
    candidates = set(names)
    values = []
    for child in list(element):
        if local_name(child.tag) in candidates or child.tag in candidates:
            value = clean_text("".join(child.itertext()))
            if present(value):
                values.append(value)
    return values


def atom_link(entry: ET.Element) -> str | None:
    for child in list(entry):
        if local_name(child.tag) != "link":
            continue
        href = child.attrib.get("href")
        rel = child.attrib.get("rel")
        if present(href) and (not present(rel) or rel == "alternate"):
            return href
    return None


def raw_id(source_id: str, raw_key: Any) -> str:
    return f"rss:{source_id}:{hashlib.sha256(str(raw_key).encode()).hexdigest()[:16]}"


def parse_rss_items(root: ET.Element, source_id: str, max_items: int) -> list[dict[str, Any]]:
    items = root.findall(".//item")[:max_items]
    result = []
    for index, item in enumerate(items):
        guid = child_text(item, "guid")
        link = child_text(item, "link")
        title = child_text(item, "title") or link or guid or "(untitled)"
        raw_key = next((value for value in [guid, link, title, index] if present(value)), index)
        payload = {
            "raw_id": raw_id(source_id, raw_key),
            "platform_item_id": guid or link,
            "guid": guid,
            "title": title,
            "link": link,
            "published_at": child_text(item, "pubDate", "published", "updated", "date"),
            "author": child_text(item, "author", "creator"),
            "summary": child_text(item, "description", "summary"),
            "content": child_text(item, "encoded", "content", "description"),
            "categories": child_values(item, "category"),
            "raw": {"source_format": "rss", "guid": guid, "link": link},
        }
        result.append({k: v for k, v in payload.items() if v is not None and v != []})
    return result


def parse_atom_items(root: ET.Element, source_id: str, max_items: int) -> list[dict[str, Any]]:
    entries = [child for child in list(root) if local_name(child.tag) == "entry"][:max_items]
    result = []
    for index, entry in enumerate(entries):
        guid = child_text(entry, "id")
        link = atom_link(entry)
        title = child_text(entry, "title") or link or guid or "(untitled)"
        raw_key = next((value for value in [guid, link, title, index] if present(value)), index)
        categories = [child.attrib.get("term") for child in list(entry) if local_name(child.tag) == "category" and child.attrib.get("term")]
        payload = {
            "raw_id": raw_id(source_id, raw_key),
            "platform_item_id": guid or link,
            "guid": guid,
            "title": title,
            "link": link,
            "published_at": child_text(entry, "published", "updated"),
            "author": child_text(entry, "author", "name"),
            "summary": child_text(entry, "summary"),
            "content": child_text(entry, "content", "summary"),
            "categories": categories,
            "raw": {"source_format": "atom", "guid": guid, "link": link},
        }
        result.append({k: v for k, v in payload.items() if v is not None and v != []})
    return result


def parse_feed(xml: str, source_id: str, max_items: int):
    root = ET.fromstring(xml)
    if local_name(root.tag) == "feed":
        return parse_atom_items(root, source_id, max_items), {"format": "atom", "title": child_text(root, "title")}
    channel = root.find(".//channel")
    metadata = {"format": "rss"}
    if channel is not None:
        for key in ["title", "link", "description"]:
            value = child_text(channel, key)
            if value is not None:
                metadata[key] = value
    return parse_rss_items(root, source_id, max_items), metadata


def error_payload(code: str, message: str, retryable: bool, item_scope: str, raw_status: str | None = None) -> dict[str, Any]:
    payload = {"code": code, "message": str(message), "retryable": retryable, "item_scope": item_scope, "raw_status": raw_status}
    return {k: v for k, v in payload.items() if v is not None}


def fetch_xml(url: str, timeout_seconds: int, user_agent: str | None):
    request = Request(url, headers={"User-Agent": user_agent} if present(user_agent) else {})
    with urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode(), response


def fetch_source(source: dict[str, Any], rules: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    source_id = source["id"]
    fetched_at = datetime.now().astimezone().isoformat()
    response = {"source_id": source_id, "source_type": source["source_type"], "provider": source["provider"], "fetched_at": fetched_at, "status": "failed", "items": [], "errors": []}
    connection = source.get("connection", {})
    if not connection.get("rss_url"):
        response["errors"].append(error_payload("invalid_config", "rss source requires connection.rss_url", False, "source"))
        return response
    try:
        xml, http_response = fetch_xml(connection["rss_url"], source.get("timeout_seconds") or rules.get("fetch", {}).get("timeout_seconds") or 20, rules.get("fetch", {}).get("user_agent"))
        items, metadata = parse_feed(xml, source_id, context.get("max_items") or rules.get("fetch", {}).get("max_items_per_source") or 50)
        response.update({"status": "ok", "items": items, "raw_feed_metadata": {k: v for k, v in metadata.items() if v is not None}})
        rate_limit = {}
        for header, key in [("x-ratelimit-limit", "limit"), ("x-ratelimit-remaining", "remaining"), ("x-ratelimit-reset", "reset_at"), ("retry-after", "retry_after_seconds")]:
            value = http_response.headers.get(header)
            if value is not None:
                rate_limit[key] = value
        if rate_limit:
            response["rate_limit"] = rate_limit
    except ET.ParseError as exc:
        response["errors"].append(error_payload("invalid_xml", str(exc).splitlines()[0], False, "source"))
    except Exception as exc:
        response["errors"].append(error_payload("rss_url_unreachable", str(exc), True, "source"))
    return response


def fetch(sources_config: dict[str, Any], rules: dict[str, Any], source_id: str | None = None, max_items: int | None = None) -> dict[str, Any]:
    run_id = f"rss-fetch-{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"
    rss_sources = [source for source in sources_config["sources"] if source.get("enabled") is not False and source.get("source_type") == "rss"]
    if source_id:
        rss_sources = [source for source in rss_sources if source["id"] == source_id]
    context = {"run_id": run_id, "fetched_at": datetime.now().astimezone().isoformat()}
    if max_items is not None:
        context["max_items"] = max_items
    return {"run_id": run_id, "adapter": "rss", "contract_version": 1, "fetched_at": context["fetched_at"], "results": [fetch_source(source, rules, context) for source in rss_sources]}
