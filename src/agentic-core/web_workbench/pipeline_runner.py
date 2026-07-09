from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from secrets import token_hex
from typing import Any


SENSITIVE_PATTERN = re.compile(r"(GITHUB_ACCESS_TOKEN|authorization|token)(\s*[:=]\s*)[^\s,;]+", re.IGNORECASE)


class PipelineRunner:
    def __init__(
        self,
        root: Path | str,
        commands: list[dict[str, Any]] | None = None,
        timeout_seconds: int = 120,
    ):
        self.root = Path(root).resolve()
        self.commands = commands
        self.timeout_seconds = timeout_seconds
        self.request_id: str | None = None
        self.current_run_id: str | None = None
        self.run_started_at: datetime | None = None
        self.adapter_summary: dict[str, Any] | None = None
        self.store_summary: dict[str, Any] | None = None
        self.signal_diff: dict[str, Any] | None = None
        self.step_results: list[dict[str, Any]] = []

    def refresh(self) -> dict[str, Any]:
        self.app_dir.mkdir(parents=True, exist_ok=True)
        lock_result = self._acquire_lock()
        if lock_result["status"] != "locked":
            return lock_result

        self.request_id = lock_result["request_id"]
        self.current_run_id = None
        self.run_started_at = datetime.now(timezone.utc)
        self.adapter_summary = None
        self.store_summary = None
        self.signal_diff = None
        self.step_results = []
        self._write_status("running", current_step=None, command_results=[])

        try:
            for command in self.commands or self._default_commands():
                self._run_step(command)
                self._validate_step(command["name"])
            self._publish_signals()
            self._cleanup_temp_dirs()
        except Exception as exc:
            status = self._write_status(
                "failed",
                last_error=self._redact(str(exc)),
                command_results=self.step_results,
            )
            self._release_lock()
            return status

        signals = self._parsed_temp_signals()
        status_name = "succeeded" if len(signals.get("signals", [])) > 0 else "succeeded_empty"
        status = self._write_status(
            status_name,
            command_results=self.step_results,
            last_successful_generated_at=signals.get("generated_at"),
            last_successful_input_run_id=signals.get("input_run_id"),
        )
        self._release_lock()
        return status

    def _default_commands(self) -> list[dict[str, Any]]:
        ruby = shutil.which("ruby") or "ruby"
        return [
            {
                "name": "fetch_rss",
                "argv": [ruby, "src/fetch_rss.rb", "--output", "data/adapter-output/rss-fetch-latest.json"],
            },
            {
                "name": "ingest_adapter_output",
                "argv": [
                    ruby,
                    "src/ingest_adapter_output.rb",
                    "--input",
                    "data/adapter-output/rss-fetch-latest.json",
                    "--output",
                    "data/canonical-items/latest.json",
                ],
            },
            {
                "name": "store_canonical_jsonl",
                "argv": [
                    ruby,
                    "src/store_canonical_jsonl.rb",
                    "--input",
                    "data/canonical-items/latest.json",
                    "--store-dir",
                    "data/store",
                ],
            },
            {
                "name": "build_signals",
                "argv": [
                    ruby,
                    "src/build_signals.rb",
                    "--input",
                    "data/canonical-items/latest.json",
                    "--profile",
                    "config/user-profile.yml",
                    "--rules",
                    "config/signal-rules.yml",
                    "--output",
                    self._temp_signals_relative_path(),
                    "--markdown",
                    self._temp_markdown_relative_path(),
                    "--html",
                    self._temp_html_relative_path(),
                ],
            },
        ]

    def _acquire_lock(self) -> dict[str, Any]:
        if self.lock_path.exists():
            try:
                lock = json.loads(self.lock_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return self._mark_stale_lock()
            if self._process_alive(lock.get("pid")):
                return {"status": "already_running", "request_id": lock.get("request_id")}
            return self._mark_stale_lock()

        request_id = f"refresh-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{token_hex(4)}"
        lock = {
            "request_id": request_id,
            "pid": os.getpid(),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with self.lock_path.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(lock))
        except FileExistsError:
            return {"status": "already_running"}
        return {"status": "locked", "request_id": request_id}

    def _mark_stale_lock(self) -> dict[str, Any]:
        status = self._write_status("failed_stale_lock", last_error="Refresh lock is stale.")
        self._release_lock()
        return status

    def _release_lock(self) -> None:
        self.lock_path.unlink(missing_ok=True)

    def _process_alive(self, pid: object) -> bool:
        try:
            os.kill(int(pid), 0)
            return True
        except (ProcessLookupError, ValueError, TypeError):
            return False
        except PermissionError:
            return True

    def _run_step(self, command: dict[str, Any]) -> None:
        name = command["name"]
        self._write_status("running", current_step=name, command_results=self.step_results)
        started_at = datetime.now(timezone.utc)
        argv = self._expanded_argv(command["argv"])
        env = {**os.environ, "REQUEST_ID": str(self.request_id)}

        try:
            completed = subprocess.run(
                argv,
                cwd=self.root,
                env=env,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            self.step_results.append(
                {
                    "name": name,
                    "exit_status": None,
                    "started_at": started_at.isoformat(),
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "stderr_tail": f"Timed out after {self.timeout_seconds} seconds.",
                }
            )
            raise RuntimeError(f"Step {name} timed out") from exc

        result = {
            "name": name,
            "exit_status": completed.returncode,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "stdout_tail": self._tail(self._redact(completed.stdout)),
            "stderr_tail": self._tail(self._redact(completed.stderr)),
        }
        self.step_results.append(result)
        self._capture_store_summary(name, completed.stdout)

        if completed.returncode != 0:
            raise RuntimeError(f"Step {name} failed with exit status {completed.returncode}")

    def _validate_step(self, name: str) -> None:
        if "fetch" in name or "adapter" in name:
            adapter_output = self._parse_json_file(self.root / "data/adapter-output/rss-fetch-latest.json")
            self._capture_adapter_summary(adapter_output)
        elif "ingest" in name or "canonical" in name:
            canonical = self._parse_json_file(self.root / "data/canonical-items/latest.json")
            self.current_run_id = canonical.get("run_id")
        elif "store" in name:
            self._validate_store_run()
        elif "signal" in name or "build" in name:
            signals = self._parsed_temp_signals()
            if self.current_run_id and signals.get("input_run_id") != self.current_run_id:
                raise RuntimeError("Signal input_run_id does not match canonical run_id")

    def _validate_store_run(self) -> None:
        if not self.current_run_id:
            return
        run_dir = self.root / "data/store/runs"
        found = any(self.current_run_id in path.read_text(encoding="utf-8") for path in run_dir.glob("*.jsonl"))
        if not found:
            raise RuntimeError("Store run record was not appended")

    def _publish_signals(self) -> None:
        previous_ids = self._latest_signal_ids()
        current_ids = self._signal_ids(self._parsed_temp_signals())
        self.signal_diff = {
            "changed": previous_ids != current_ids,
            "previous_count": len(previous_ids),
            "current_count": len(current_ids),
            "added_ids": [signal_id for signal_id in current_ids if signal_id not in previous_ids],
            "removed_ids": [signal_id for signal_id in previous_ids if signal_id not in current_ids],
        }
        self.latest_signals_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_publish_path = self.latest_signals_path.with_name(f"{self.latest_signals_path.name}.{self.request_id}.tmp")
        shutil.copyfile(self.temp_signals_path, tmp_publish_path)
        tmp_publish_path.replace(self.latest_signals_path)

    def _parsed_temp_signals(self) -> dict[str, Any]:
        return self._parse_json_file(self.temp_signals_path)

    def _write_status(self, status: str, **extra: Any) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        payload = {
            "status": status,
            "started_at": self.run_started_at.isoformat() if self.run_started_at else extra.get("started_at"),
            "finished_at": None if status == "running" else now.isoformat(),
            "duration_seconds": None
            if status == "running" or self.run_started_at is None
            else round(time.monotonic() - self._run_started_monotonic, 3)
            if hasattr(self, "_run_started_monotonic")
            else None,
            "current_step": extra.get("current_step"),
            "last_error": extra.get("last_error"),
            "command_results": extra.get("command_results") or [],
            "adapter_summary": self.adapter_summary,
            "store_summary": self.store_summary,
            "signal_diff": self.signal_diff,
            "last_successful_generated_at": extra.get("last_successful_generated_at"),
            "last_successful_input_run_id": extra.get("last_successful_input_run_id"),
        }
        if status == "running" and not hasattr(self, "_run_started_monotonic"):
            self._run_started_monotonic = time.monotonic()
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        self.status_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return payload

    def _parse_json_file(self, path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise RuntimeError(f"Expected JSON artifact missing: {path}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Expected JSON artifact is corrupt: {path}: {exc}") from exc

    def _expanded_argv(self, argv: list[object]) -> list[str]:
        return [str(value).replace("$REQUEST_ID", str(self.request_id)) for value in argv]

    def _redact(self, value: str) -> str:
        return SENSITIVE_PATTERN.sub(r"\1\2[REDACTED]", str(value))

    def _tail(self, value: str) -> str:
        return "".join(str(value).splitlines(keepends=True)[-20:])

    def _capture_store_summary(self, name: str, stdout: str) -> None:
        if name not in {"store_canonical_jsonl", "store"}:
            return
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            self.store_summary = None
            return
        self.store_summary = {
            key: parsed[key]
            for key in ("input_items", "appended_items", "skipped_duplicates", "dropped_items")
            if key in parsed
        }

    def _capture_adapter_summary(self, payload: dict[str, Any]) -> None:
        results = payload.get("results")
        if not isinstance(results, list):
            self.adapter_summary = None
            return

        source_results = []
        status_counts: dict[str, int] = {}
        item_count = 0
        for result in results:
            if not isinstance(result, dict):
                continue
            status = str(result.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
            items = result.get("items")
            items_count = len(items) if isinstance(items, list) else 0
            item_count += items_count
            errors = result.get("errors") if isinstance(result.get("errors"), list) else []
            source_results.append(
                {
                    "source_id": result.get("source_id"),
                    "status": status,
                    "item_count": items_count,
                    "errors": [
                        {
                            "code": error.get("code"),
                            "message": self._redact(str(error.get("message") or "")),
                            "retryable": error.get("retryable"),
                        }
                        for error in errors
                        if isinstance(error, dict)
                    ],
                }
            )

        self.adapter_summary = {
            "total_sources": len(source_results),
            "ok_sources": status_counts.get("ok", 0),
            "partial_sources": status_counts.get("partial", 0),
            "failed_sources": status_counts.get("failed", 0),
            "items": item_count,
            "source_results": source_results,
        }

    def _signal_ids(self, payload: dict[str, Any]) -> list[str]:
        return [str(signal.get("id", "")) for signal in payload.get("signals", [])]

    def _latest_signal_ids(self) -> list[str]:
        try:
            return self._signal_ids(self._parse_json_file(self.latest_signals_path))
        except RuntimeError:
            return []

    def _cleanup_temp_dirs(self, keep: int = 5) -> None:
        tmp_root = self.root / "data/app/tmp"
        if not tmp_root.exists():
            return
        dirs = [path for path in tmp_root.iterdir() if path.is_dir()]
        for path in dirs:
            if path.name == "$REQUEST_ID":
                shutil.rmtree(path)
        refresh_dirs = sorted(
            [path for path in dirs if path.name != "$REQUEST_ID" and path.exists()],
            key=lambda path: path.stat().st_mtime,
        )
        for path in refresh_dirs[: max(len(refresh_dirs) - keep, 0)]:
            shutil.rmtree(path)

    @property
    def app_dir(self) -> Path:
        return self.root / "data/app"

    @property
    def status_path(self) -> Path:
        return self.root / "data/app/refresh-status.json"

    @property
    def lock_path(self) -> Path:
        return self.root / "data/app/refresh.lock"

    @property
    def latest_signals_path(self) -> Path:
        return self.root / "data/signals/latest.json"

    @property
    def temp_signals_path(self) -> Path:
        return self.root / self._temp_signals_relative_path()

    def _temp_signals_relative_path(self) -> str:
        return f"data/app/tmp/{self.request_id or '$REQUEST_ID'}/signals.json"

    def _temp_markdown_relative_path(self) -> str:
        return f"data/app/tmp/{self.request_id or '$REQUEST_ID'}/dashboard.md"

    def _temp_html_relative_path(self) -> str:
        return f"data/app/tmp/{self.request_id or '$REQUEST_ID'}/generated-latest.html"
