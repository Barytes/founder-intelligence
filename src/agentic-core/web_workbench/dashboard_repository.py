from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import yaml


EMPTY_SIGNALS = {
    "status": "empty",
    "message": "No successful signals have been generated yet.",
}


class DashboardRepository:
    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()

    def latest_signals(self) -> dict:
        path = self._path("data/signals/latest.json")
        if not path.exists():
            return dict(EMPTY_SIGNALS)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {
                "status": "error",
                "message": "Local signal file is corrupt or unreadable.",
            }

    def latest_run(self) -> dict:
        run_files = sorted(self._path("data/store/runs").glob("*.jsonl"))
        if not run_files:
            return {
                "status": "empty",
                "message": "No store runs have been recorded yet.",
            }
        try:
            lines = run_files[-1].read_text(encoding="utf-8").splitlines()
            last_line = next((line for line in reversed(lines) if line.strip()), None)
            if last_line is None:
                return {
                    "status": "empty",
                    "message": "No store runs have been recorded yet.",
                }
            return json.loads(last_line)
        except json.JSONDecodeError:
            return {
                "status": "error",
                "message": "Latest store run is corrupt or unreadable.",
            }

    def refresh_status(self) -> dict:
        path = self._path("data/app/refresh-status.json")
        if not path.exists():
            return {"status": "idle"}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {
                "status": "error",
                "message": "Refresh status file is corrupt or unreadable.",
            }

    def profile(self) -> dict:
        path = self._path("config/user-profile.yml")
        try:
            return {
                "path": "config/user-profile.yml",
                "content": path.read_text(encoding="utf-8"),
            }
        except FileNotFoundError:
            return {
                "status": "error",
                "message": "config/user-profile.yml is missing.",
            }

    def update_profile(self, content: object) -> dict:
        if not isinstance(content, str):
            return {"status": "error", "message": "Profile content must be a string."}
        try:
            config = self._parse_yaml_mapping(content)
        except yaml.YAMLError as exc:
            return {"status": "error", "message": f"Invalid YAML: {exc}"}

        error = self._validate_profile_config(config)
        if error:
            return {"status": "error", "message": error}

        normalized = content if content.endswith("\n") else f"{content}\n"
        self._write_file("config/user-profile.yml", normalized)
        return {"status": "saved", "path": "config/user-profile.yml"}

    def sources(self) -> dict:
        path = self._path("config/sources.yml")
        try:
            content = path.read_text(encoding="utf-8")
            config = self._parse_yaml_mapping(content)
        except FileNotFoundError:
            return {
                "status": "error",
                "message": "config/sources.yml is missing.",
            }
        except yaml.YAMLError as exc:
            return {
                "status": "error",
                "message": f"Invalid sources YAML: {exc}",
            }
        return {
            "path": "config/sources.yml",
            "content": content,
            "sources": self._source_rows(config),
        }

    def update_sources(self, content: object) -> dict:
        if not isinstance(content, str):
            return {"status": "error", "message": "Sources content must be a string."}
        try:
            config = self._parse_yaml_mapping(content)
        except yaml.YAMLError as exc:
            return {"status": "error", "message": f"Invalid sources YAML: {exc}"}

        error = self._validate_sources_config(config)
        if error:
            return {"status": "error", "message": error}

        normalized = content if content.endswith("\n") else f"{content}\n"
        self._write_file("config/sources.yml", normalized)
        return {
            "status": "saved",
            "path": "config/sources.yml",
            "content": normalized,
            "sources": self._source_rows(config),
        }

    def update_source_enabled(self, source_id: str, enabled: object) -> dict:
        if enabled not in {True, False}:
            return {"status": "error", "message": "enabled must be true or false."}

        try:
            config = self._sources_config()
        except yaml.YAMLError as exc:
            return {"status": "error", "message": f"Invalid sources YAML: {exc}"}

        source = next(
            (candidate for candidate in config.get("sources", []) if candidate.get("id") == source_id),
            None,
        )
        if source is None:
            return {"status": "not_found", "message": "Source not found."}
        if source.get("source_type") != "rss":
            return {
                "status": "error",
                "message": "Only RSS sources can be toggled in the current MVP.",
            }

        source["enabled"] = enabled
        self._write_file("config/sources.yml", yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
        return {"status": "saved", "source": self._source_row(source)}

    def _sources_config(self) -> dict:
        return self._parse_yaml_mapping(self._path("config/sources.yml").read_text(encoding="utf-8"))

    def _parse_yaml_mapping(self, content: str) -> dict:
        parsed = yaml.safe_load(content) or {}
        return parsed if isinstance(parsed, dict) else {}

    def _validate_profile_config(self, config: dict) -> str | None:
        if not isinstance(config, dict) or "version" not in config:
            return "Profile YAML must be a mapping with a version field."
        if not isinstance(config.get("user"), dict):
            return "Profile user must be a mapping."
        if self._blank(config.get("user", {}).get("name")):
            return "Profile user.name is required."

        goals = config.get("goals", [])
        if not isinstance(goals, list):
            return "Profile goals must be an array."
        for index, goal in enumerate(goals):
            if not isinstance(goal, dict):
                return f"Profile goal at index {index} must be a mapping."
            if self._blank(goal.get("title")) and not self._array_of_strings(goal.get("keywords"), allow_empty=False):
                return f"Profile goal at index {index} must include title or keywords."

        terms: list[object] = []
        if isinstance(config.get("interests"), list):
            terms.extend(config["interests"])
        if isinstance(config.get("watch_entities"), list):
            terms.extend(config["watch_entities"])
        for goal in goals:
            if isinstance(goal, dict) and isinstance(goal.get("keywords"), list):
                terms.extend(goal["keywords"])
        if not any(not self._blank(term) for term in terms):
            return "Profile must include at least one interest, watch_entity, or goal keyword."

        if "interests" in config and not self._array_of_strings(config["interests"], allow_empty=False):
            return "Profile interests must be an array of strings."
        if "watch_entities" in config and not self._array_of_strings(config["watch_entities"], allow_empty=True):
            return "Profile watch_entities must be an array of strings."
        if "negative_preferences" in config and not self._array_of_strings(config["negative_preferences"], allow_empty=True):
            return "Profile negative_preferences must be an array of strings."
        output = config.get("output_preferences")
        if output is not None:
            if not isinstance(output, dict):
                return "Profile output_preferences must be a mapping."
            top_n = output.get("default_top_n")
            if top_n is not None and (not isinstance(top_n, int) or top_n <= 0):
                return "Profile output_preferences.default_top_n must be a positive integer."
        return None

    def _validate_sources_config(self, config: dict) -> str | None:
        if not isinstance(config, dict) or "version" not in config:
            return "Sources YAML must be a mapping with a version field."
        sources = config.get("sources")
        if not isinstance(sources, list):
            return "Sources YAML must include a sources array."

        seen_ids: set[str] = set()
        for index, source in enumerate(sources):
            if not isinstance(source, dict):
                return f"Source at index {index} must be a mapping."
            source_id = source.get("id")
            if self._blank(source_id):
                return f"Source at index {index} must include id."
            if source_id in seen_ids:
                return f"Duplicate source id: {source_id}."
            seen_ids.add(source_id)

            source_type = source.get("source_type")
            for key in ("source_type", "name", "provider", "category"):
                if self._blank(source.get(key)):
                    return f"Source {source_id} must include {key}."
            if source.get("enabled") not in {True, False}:
                return f"Source {source_id} enabled must be true or false."
            if "tags" in source and not self._array_of_strings(source["tags"], allow_empty=True):
                return f"Source {source_id} tags must be an array of strings."
            schedule_error = self._validate_schedule(source, f"Source {source_id}")
            if schedule_error:
                return schedule_error

            if source_type == "rss":
                connection = source.get("connection")
                if not isinstance(connection, dict):
                    return f"Source {source_id} connection must be a mapping."
                if not self._valid_http_url(connection.get("rss_url")):
                    return f"Source {source_id} connection.rss_url must be http or https."
            elif source.get("enabled"):
                return (
                    f"Source {source_id} uses unsupported source_type {source_type}; "
                    "only RSS sources can be enabled in the current MVP."
                )

        templates = config.get("source_templates", {})
        if not isinstance(templates, dict):
            return "source_templates must be a mapping."
        for template_id, template in templates.items():
            if not isinstance(template, dict):
                return f"Source template {template_id} must be a mapping."
            if self._blank(template.get("source_type")):
                return f"Source template {template_id} must include source_type."
            if template.get("enabled") is True:
                return f"Source template {template_id} must not be enabled in the current MVP."
            schedule_error = self._validate_schedule(template, f"Source template {template_id}")
            if schedule_error:
                return schedule_error
        return None

    def _validate_schedule(self, source: dict, label: str) -> str | None:
        if "schedule" not in source:
            return None
        schedule = source["schedule"]
        if not isinstance(schedule, dict):
            return f"{label} schedule must be a mapping."
        minutes = schedule.get("refresh_interval_minutes")
        if minutes is None:
            return None
        if not isinstance(minutes, int) or minutes <= 0:
            return f"{label} schedule.refresh_interval_minutes must be a positive integer."
        return None

    def _source_rows(self, config: dict) -> list[dict]:
        rows = [self._source_row(source) for source in config.get("sources", [])]
        for source_id, template in config.get("source_templates", {}).items():
            row_source = {**template, "id": source_id, "template": True, "enabled": False}
            rows.append(self._source_row(row_source))
        return rows

    def _source_row(self, source: dict) -> dict:
        source_type = source.get("source_type") or source.get("type")
        enabled = source.get("enabled", False)
        toggleable = source_type == "rss" and not source.get("template")
        schedule_minutes = source.get("schedule", {}).get("refresh_interval_minutes")
        return {
            "id": source.get("id"),
            "name": source.get("name") or source.get("id"),
            "category": source.get("category") or "uncategorized",
            "type": source_type or "unknown",
            "provider": source.get("provider"),
            "enabled": enabled,
            "toggleable": toggleable,
            "runnable": toggleable and enabled,
            "cadence": f"{schedule_minutes} min" if schedule_minutes else "manual",
            "priority": source.get("priority"),
            "tags": source.get("tags") or [],
            "notes": source.get("notes"),
            "signal": source.get("notes")
            or source.get("connection", {}).get("rss_url")
            or source.get("connection", {}).get("tool")
            or "Configured source",
        }

    def _array_of_strings(self, value: object, *, allow_empty: bool) -> bool:
        if not isinstance(value, list):
            return False
        if not allow_empty and not value:
            return False
        return all(isinstance(entry, str) and not self._blank(entry) for entry in value)

    def _valid_http_url(self, value: object) -> bool:
        parsed = urlparse(str(value or ""))
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def _blank(self, value: object) -> bool:
        return value is None or str(value).strip() == ""

    def _path(self, path: str) -> Path:
        return self.root / path

    def _write_file(self, path: str, content: str) -> None:
        full_path = self._path(path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = full_path.with_name(f"{full_path.name}.tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(full_path)

