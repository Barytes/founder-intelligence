import json
from datetime import datetime
from pathlib import Path
from typing import Any


def present(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def partition_date(options: dict[str, Any]) -> str:
    if present(options.get("date")):
        return str(options["date"])
    return datetime.now().strftime("%Y-%m-%d")


def jsonl_existing_ids(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    ids = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        if present(record.get("id")):
            ids[record["id"]] = line_number
    return ids


def validate_item(item: dict[str, Any], index: int) -> None:
    required = ["id", "source_id", "source_type", "provider", "title", "fetched_at", "content_hash", "dedupe_key"]
    missing = [field for field in required if not present(item.get(field))]
    if missing:
        raise RuntimeError(f"item {index} missing required fields: {', '.join(missing)}")


def append_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def store(canonical: dict[str, Any], options: dict[str, Any], stored_at: str | None = None) -> dict[str, Any]:
    date = partition_date(options)
    store_dir = Path(options["store_dir"])
    items_path = store_dir / "items" / f"{date}.jsonl"
    runs_path = store_dir / "runs" / f"{date}.jsonl"
    stored_at = stored_at or datetime.now().astimezone().isoformat()
    items = canonical["items"]
    existing_ids = jsonl_existing_ids(items_path)
    appended = []
    skipped = []
    for index, item in enumerate(items):
        validate_item(item, index)
        item_id = item["id"]
        if item_id in existing_ids:
            skipped.append({"id": item_id, "source_id": item["source_id"], "reason": "duplicate_id", "existing_line": existing_ids[item_id]})
            continue
        appended.append({**item, "stored_at": stored_at, "store_partition": date, "input_run_id": canonical.get("run_id")})
        existing_ids[item_id] = len(existing_ids) + len(appended)

    append_jsonl(items_path, appended)
    run_record = {
        "stored_at": stored_at,
        "store_partition": date,
        "input_run_id": canonical.get("run_id"),
        "input_adapter": canonical.get("input_adapter"),
        "items_path": str(items_path),
        "input_items": len(items),
        "appended_items": len(appended),
        "skipped_duplicates": len(skipped),
        "dropped_items": canonical.get("summary", {}).get("dropped_items"),
        "skipped": skipped,
    }
    append_jsonl(runs_path, [run_record])
    return {
        "items_path": str(items_path),
        "runs_path": str(runs_path),
        "input_items": len(items),
        "appended_items": len(appended),
        "skipped_duplicates": len(skipped),
    }


def run(input_path: Path, store_dir: Path, date: str | None = None) -> dict[str, Any]:
    canonical = json.loads(input_path.read_text(encoding="utf-8"))
    return store(canonical, {"store_dir": str(store_dir), "date": date})
