import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
import secrets
import shutil
from typing import Any

import yaml

from agentic_core.feature_flags import L4FeatureFlags, load_l4_feature_flags
from agentic_core.l4.database import Database
from agentic_core.l4.repositories import ProfileRepository
from agentic_core.l4.source_catalog import SourceCatalog, snapshot_to_sources_config
from agentic_core.pipeline import build_signals, fetch_rss, ingest_adapter_output, store_canonical_jsonl


SENSITIVE_VALUE_PATTERN = re.compile(
    r"(?i)(?:github_access_token|authorization|token)\s*[:=]\s*[^\s,;]+"
)


class PipelineRunner:
    def __init__(
        self,
        root: str | Path,
        timeout_seconds: int = 120,
        *,
        l4_feature_flags: L4FeatureFlags | None = None,
        profile_repository: ProfileRepository | None = None,
        source_catalog: SourceCatalog | None = None,
        user_id: str = "local-user",
        l4_database: Database | None = None,
        profile_service: Any | None = None,
        source_discovery_service: Any | None = None,
        ranking_service: Any | None = None,
        inbox_repository: Any | None = None,
        workflow_repository: Any | None = None,
    ):
        self.root = Path(root).resolve()
        self.timeout_seconds = timeout_seconds
        self.request_id: str | None = None
        self.current_run_id: str | None = None
        self.run_started_at: datetime | None = None
        self.store_summary: dict[str, Any] | None = None
        self.signal_diff: dict[str, Any] | None = None
        self.adapter_summary: dict[str, Any] | None = None
        self.step_results: list[dict[str, Any]] = []
        self.l4_feature_flags = l4_feature_flags or load_l4_feature_flags()
        self.profile_repository = profile_repository
        self.user_id = user_id
        self.source_catalog = source_catalog
        self.l4_database = l4_database
        self.profile_service = profile_service
        self.source_discovery_service = source_discovery_service
        self.ranking_service = ranking_service
        self.inbox_repository = inbox_repository
        self.workflow_repository = workflow_repository
        self.source_snapshot = None
        self.resolved_sources_config: dict[str, Any] | None = None
        self.workflow_run_id: str | None = None
        self.profile_id: str | None = None
        self.agent_stage_status: str | None = None
        self.degraded_reasons: list[str] = []
        self.workflow_usage: dict[str, Any] = {}

    def refresh(self) -> dict[str, Any]:
        if self.l4_feature_flags.workflow_enabled:
            from agentic_core.l4.workflow import L4WorkflowRunner

            return L4WorkflowRunner(self).refresh()
        self.app_dir().mkdir(parents=True, exist_ok=True)
        lock_result = self.acquire_lock()
        if lock_result["status"] != "locked":
            return lock_result
        self.request_id = lock_result["request_id"]
        self.run_started_at = datetime.now().astimezone()
        self.step_results = []
        self.store_summary = None
        self.signal_diff = None
        self.adapter_summary = None
        self.source_snapshot = None
        self.resolved_sources_config = None
        self.write_status("running", {"current_step": None, "command_results": []})
        try:
            self.step_fetch_rss()
            self.step_ingest_adapter_output()
            self.step_store_canonical_jsonl()
            self.step_build_signals()
            self.publish_signals()
            self.cleanup_temp_dirs()
        except Exception as exc:
            status = self.write_status("failed", {"last_error": str(exc), "command_results": self.step_results})
            self.release_lock()
            return status
        signal_count = len(self.parsed_temp_signals().get("signals", []))
        if self.adapter_summary and self.adapter_summary["failed_sources"] + self.adapter_summary["partial_sources"] > 0:
            status_name = "succeeded_partial"
        else:
            status_name = "succeeded" if signal_count > 0 else "succeeded_empty"
        status = self.write_status(
            status_name,
            {
                "command_results": self.step_results,
                "last_successful_generated_at": self.parsed_temp_signals().get("generated_at"),
                "last_successful_input_run_id": self.parsed_temp_signals().get("input_run_id"),
            },
        )
        self.release_lock()
        return status

    def step_fetch_rss(self) -> None:
        self.run_step("fetch_rss", self._step_fetch_rss)

    def _step_fetch_rss(self):
        sources = self._resolve_sources_config()
        rules = yaml.safe_load((self.root / "config/ingestion-rules.yml").read_text(encoding="utf-8"))
        output = fetch_rss.fetch(sources, rules)
        self.write_json(self.root / "data/adapter-output/rss-fetch-latest.json", output)
        self.adapter_summary = self.summarize_adapter_output(output)

    def step_ingest_adapter_output(self) -> None:
        self.run_step("ingest_adapter_output", self._step_ingest_adapter_output)

    def _step_ingest_adapter_output(self):
        output = ingest_adapter_output.run(
            self.root / "data/adapter-output/rss-fetch-latest.json",
            None if self.resolved_sources_config is not None else self.root / "config/sources.yml",
            self.root / "config/ingestion-rules.yml",
            self.root / "data/canonical-items/latest.json",
            sources_override=self.resolved_sources_config,
        )
        self.current_run_id = output.get("run_id")

    def step_store_canonical_jsonl(self) -> None:
        self.run_step("store_canonical_jsonl", self._step_store_canonical_jsonl)

    def _step_store_canonical_jsonl(self):
        self.store_summary = store_canonical_jsonl.run(self.root / "data/canonical-items/latest.json", self.root / "data/store")

    def step_build_signals(self) -> None:
        self.run_step("build_signals", self._step_build_signals)

    def _step_build_signals(self):
        profile_path: Path | None = self.root / "config/user-profile.yml"
        profile_override = None
        profile_id = None
        profile_hash = None
        profile_status = None
        owned_database: Database | None = None
        if self.l4_feature_flags.profile_enabled:
            repository = self.profile_repository
            if repository is None:
                owned_database = Database(
                    self.root / "data/app/founder-intelligence.db"
                )
                repository = ProfileRepository(owned_database)
            effective = repository.resolve_effective_profile(self.user_id)
            profile_path = None
            profile_override = self._legacy_profile_view(effective.fields)
            profile_id = effective.profile_id
            profile_hash = effective.profile_hash
            profile_status = "active" if effective.initialized else "uninitialized"
        try:
            build_signals.run(
                self.root / "data/canonical-items/latest.json",
                profile_path,
                self.root / "config/signal-rules.yml",
                self.temp_signals_path(),
                self.temp_markdown_path(),
                self.temp_html_path(),
                profile_override=profile_override,
                profile_id=profile_id,
                profile_hash=profile_hash,
                profile_status=profile_status,
            )
        finally:
            if owned_database is not None:
                owned_database.close()
        signals = self.parsed_temp_signals()
        if self.current_run_id and signals.get("input_run_id") != self.current_run_id:
            raise RuntimeError("Signal input_run_id does not match canonical run_id")

    def _resolve_sources_config(self) -> dict[str, Any]:
        if not self.l4_feature_flags.source_catalog_enabled:
            return yaml.safe_load(
                (self.root / "config/sources.yml").read_text(encoding="utf-8")
            )
        catalog = self.source_catalog
        owned_database = None
        if catalog is None:
            owned_database = Database(
                self.root / "data/app/founder-intelligence.db"
            )
            catalog = SourceCatalog(owned_database)
        try:
            self.source_snapshot = catalog.create_snapshot(
                snapshot_id=f"source-snapshot-{self.request_id}",
                workflow_run_id=self.request_id,
            )
            self.resolved_sources_config = snapshot_to_sources_config(
                self.source_snapshot
            )
            return self.resolved_sources_config
        finally:
            if owned_database is not None:
                owned_database.close()

    @staticmethod
    def _legacy_profile_view(fields: dict[str, Any]) -> dict[str, Any]:
        profile = dict(fields)
        active_goals = profile.pop("active_goals", [])
        if active_goals and "goals" not in profile:
            profile["goals"] = [
                goal if isinstance(goal, dict) else {"title": str(goal), "keywords": []}
                for goal in active_goals
            ]
        return profile

    def run_step(self, name: str, callback) -> None:
        self.write_status("running", {"current_step": name, "command_results": self.step_results})
        started_at = datetime.now().astimezone()
        result = {"name": name, "exit_status": 0, "started_at": started_at.isoformat()}
        try:
            callback()
            result["finished_at"] = datetime.now().astimezone().isoformat()
            result["stdout_tail"] = ""
            result["stderr_tail"] = ""
            self.step_results.append(result)
        except Exception as exc:
            result["exit_status"] = 1
            result["finished_at"] = datetime.now().astimezone().isoformat()
            result["stderr_tail"] = str(exc)
            self.step_results.append(result)
            raise

    def acquire_lock(self) -> dict[str, Any]:
        lock_path = self.lock_path()
        if lock_path.exists():
            lock = self.parse_json_file(lock_path)
            if self.process_alive(lock.get("pid")):
                return {"status": "already_running", "request_id": lock.get("request_id")}
            status = self.write_status("failed_stale_lock", {"last_error": "Refresh lock is stale."})
            self.release_lock()
            return status
        request_id = f"refresh-{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(json.dumps({"request_id": request_id, "pid": os.getpid(), "started_at": datetime.now().astimezone().isoformat()}), encoding="utf-8")
        return {"status": "locked", "request_id": request_id}

    def process_alive(self, pid: Any) -> bool:
        if not pid:
            return False
        try:
            os.kill(int(pid), 0)
            return True
        except (OSError, TypeError, ValueError):
            return False

    def release_lock(self) -> None:
        self.lock_path().unlink(missing_ok=True)

    def publish_signals(self) -> None:
        previous_ids = self.latest_signal_ids()
        current_ids = self.signal_ids(self.parsed_temp_signals())
        self.signal_diff = {"changed": previous_ids != current_ids, "previous_count": len(previous_ids), "current_count": len(current_ids), "added_ids": [i for i in current_ids if i not in previous_ids], "removed_ids": [i for i in previous_ids if i not in current_ids]}
        self.latest_signals_path().parent.mkdir(parents=True, exist_ok=True)
        tmp_publish_path = self.latest_signals_path().with_name(f"{self.latest_signals_path().name}.{self.request_id}.tmp")
        shutil.copyfile(self.temp_signals_path(), tmp_publish_path)
        tmp_publish_path.replace(self.latest_signals_path())

    def write_status(self, status: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        extra = extra or {}
        now = datetime.now().astimezone()
        payload = {
            "status": status,
            "started_at": self.run_started_at.isoformat() if self.run_started_at else extra.get("started_at"),
            "finished_at": None if status == "running" else now.isoformat(),
            "duration_seconds": None if status == "running" or not self.run_started_at else round((now - self.run_started_at).total_seconds(), 3),
            "current_step": extra.get("current_step"),
            "last_error": extra.get("last_error"),
            "command_results": extra.get("command_results") or [],
            "adapter_summary": self.adapter_summary,
            "store_summary": self.store_summary,
            "signal_diff": self.signal_diff,
            "request_id": self.request_id,
            "last_successful_generated_at": extra.get("last_successful_generated_at"),
            "last_successful_input_run_id": extra.get("last_successful_input_run_id"),
            "source_snapshot_id": (
                self.source_snapshot.snapshot_id if self.source_snapshot else None
            ),
            "workflow_run_id": self.workflow_run_id,
            "profile_id": self.profile_id,
            "step_results": extra.get("command_results") or [],
            "agent_stage_status": self.agent_stage_status,
            "degraded_reasons": list(self.degraded_reasons),
            "usage": dict(self.workflow_usage),
        }
        self.write_json(self.status_path(), payload)
        return payload

    def summarize_adapter_output(self, output: dict[str, Any]) -> dict[str, Any]:
        counts = {"ok": 0, "partial": 0, "failed": 0, "skipped": 0}
        source_results = []
        for result in output.get("results", []):
            status = str(result.get("status") or "failed")
            if status in counts:
                counts[status] += 1
            else:
                counts["failed"] += 1
            errors = []
            for error in result.get("errors", []):
                if not isinstance(error, dict):
                    continue
                errors.append(
                    {
                        key: self.redact_sensitive_text(value) if key == "message" else value
                        for key, value in error.items()
                        if key in {"code", "message", "retryable", "item_scope", "raw_status"}
                    }
                )
            source_results.append(
                {
                    "source_id": result.get("source_id"),
                    "status": status,
                    "item_count": len(result.get("items", [])),
                    "errors": errors,
                }
            )
        return {
            "total_sources": len(source_results),
            "ok_sources": counts["ok"],
            "partial_sources": counts["partial"],
            "failed_sources": counts["failed"],
            "skipped_sources": counts["skipped"],
            "items": sum(source["item_count"] for source in source_results),
            "source_results": source_results,
        }

    @staticmethod
    def redact_sensitive_text(value: Any) -> str:
        return SENSITIVE_VALUE_PATTERN.sub("[REDACTED]", str(value))

    def parsed_temp_signals(self):
        return self.parse_json_file(self.temp_signals_path())

    def parse_json_file(self, path: Path):
        return json.loads(path.read_text(encoding="utf-8"))

    def write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def signal_ids(self, payload: dict[str, Any]) -> list[str]:
        return [signal["id"] for signal in payload.get("signals", []) if signal.get("id")]

    def latest_signal_ids(self) -> list[str]:
        if not self.latest_signals_path().exists():
            return []
        return self.signal_ids(self.parse_json_file(self.latest_signals_path()))

    def cleanup_temp_dirs(self, keep: int = 5) -> None:
        app_tmp = self.app_dir() / "tmp"
        if not app_tmp.exists():
            return
        dirs = sorted([path for path in app_tmp.iterdir() if path.is_dir()])
        for path in dirs[:-keep]:
            shutil.rmtree(path, ignore_errors=True)

    def app_dir(self) -> Path:
        return self.root / "data/app"

    def status_path(self) -> Path:
        return self.app_dir() / "refresh-status.json"

    def lock_path(self) -> Path:
        return self.app_dir() / "refresh.lock"

    def latest_signals_path(self) -> Path:
        return self.root / "data/signals/latest.json"

    def temp_dir(self) -> Path:
        return self.app_dir() / "tmp" / str(self.request_id)

    def temp_signals_path(self) -> Path:
        return self.temp_dir() / "signals.json"

    def temp_markdown_path(self) -> Path:
        return self.temp_dir() / "dashboard.md"

    def temp_html_path(self) -> Path:
        return self.temp_dir() / "generated-latest.html"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Python Founder Intelligence pipeline")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--timeout-seconds", type=int, default=120, help="Step timeout seconds")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    status = PipelineRunner(root=args.root, timeout_seconds=args.timeout_seconds).refresh()
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
