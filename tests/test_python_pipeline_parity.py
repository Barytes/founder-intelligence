import json
import subprocess
from pathlib import Path

import yaml

from agentic_core.pipeline import build_signals as py_build_signals
from agentic_core.pipeline import ingest_adapter_output as py_ingest
from agentic_core.pipeline.fetch_rss import parse_feed
from agentic_core.pipeline.runner import PipelineRunner


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_yaml(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sample_sources():
    return {
        "version": 1,
        "sources": [
            {
                "id": "demo-rss",
                "name": "Demo RSS",
                "source_type": "rss",
                "provider": "demo",
                "fetcher": "rsshub",
                "enabled": True,
                "priority": "high",
                "category": "developer_trends",
                "connection": {"rss_url": "http://localhost:1200/demo"},
                "tags": ["AI Agent", "context"],
            }
        ],
    }


def sample_ingestion_rules():
    return {
        "version": 1,
        "fetch": {"timeout_seconds": 5, "max_items_per_source": 20, "user_agent": "test-agent"},
        "normalization": {
            "strip_html": True,
            "collapse_whitespace": True,
            "max_summary_chars": 120,
            "max_content_chars": 240,
            "remove_tracking_params": ["utm_source", "utm_medium"],
            "preserve_raw_payload": False,
        },
        "deduplication": {
            "content_hash": {"fields": ["title", "normalized_link", "summary", "content"]},
            "global_strategy": ["guid", "normalized_link", "content_hash"],
            "provider_overrides": {},
        },
        "canonical_item": {
            "required_fields": ["id", "source_id", "source_type", "provider", "title", "fetched_at", "content_hash", "dedupe_key"]
        },
        "quality_gates": {
            "flag_item_when": {"content_empty": True, "published_at_empty": True, "author_empty": True},
            "drop_item_when": {"title_empty": True},
        },
    }


def sample_adapter_output():
    return {
        "run_id": "rss-fetch-test",
        "adapter": "rss",
        "contract_version": 1,
        "fetched_at": "2026-07-09T08:00:00+08:00",
        "results": [
            {
                "source_id": "demo-rss",
                "source_type": "rss",
                "provider": "demo",
                "fetched_at": "2026-07-09T08:00:00+08:00",
                "status": "ok",
                "items": [
                    {
                        "raw_id": "raw-1",
                        "guid": "guid-1",
                        "title": "AI Agent Runtime ships",
                        "link": "https://example.com/a?utm_source=x&keep=1#frag",
                        "published_at": "2026-07-09T07:00:00+08:00",
                        "author": "",
                        "summary": "<p>Agent workflow and context memory update.</p>",
                        "content": "<p>Agent workflow and context memory update for founder intelligence.</p>",
                    },
                    {
                        "raw_id": "raw-dup",
                        "guid": "guid-1",
                        "title": "AI Agent Runtime ships",
                        "link": "https://example.com/a?utm_source=x&keep=1#frag",
                        "published_at": "2026-07-09T07:00:00+08:00",
                        "summary": "Duplicate",
                        "content": "Duplicate",
                    },
                ],
                "errors": [],
            }
        ],
    }


def sample_profile():
    return {
        "version": 1,
        "user": {"name": "Founder"},
        "interests": ["AI Agent", "context memory"],
        "watch_entities": ["Founder Intelligence"],
        "negative_preferences": ["celebrity gossip"],
        "output_preferences": {"default_top_n": 5},
    }


def sample_signal_rules():
    return {
        "version": 1,
        "keyword_rules": [
            {"tag": "ai-agent", "label": "AI Agent", "terms": ["AI Agent", "agent workflow"]},
            {"tag": "context", "label": "Context", "terms": ["context", "memory"]},
        ],
        "scoring": {
            "priority_weights": {"high": 1.2, "medium": 0.5},
            "source_type_weights": {"rss": 0.4},
            "recency": {"same_day": 0.7, "within_3_days": 0.4, "older": 0.1, "unknown": 0.0},
            "clamp": {"min": 1, "max": 5},
        },
        "recommendation": {"top_n": 5, "min_relevance_score": 1, "max_summary_sentences": 2, "max_questions": 3, "max_risks": 2},
        "filters": {"excluded_sources": [], "excluded_categories": []},
        "question_templates": ["What changed?"],
        "risk_templates": ["Verify source quality."],
    }


def test_python_ingest_normalizes_and_deduplicates_fixture():
    output = py_ingest.ingest(
        sample_adapter_output(),
        sample_sources(),
        sample_ingestion_rules(),
        now_iso="2026-07-09T09:00:00+08:00",
    )
    assert output["summary"] == {"input_results": 1, "canonical_items": 1, "dropped_items": 1}
    assert output["items"][0]["normalized_link"] == "https://example.com/a?keep=1"
    assert output["dropped_items"][0]["reason"] == "duplicate"


def test_python_build_signals_preserves_dashboard_display_contract():
    canonical = py_ingest.ingest(sample_adapter_output(), sample_sources(), sample_ingestion_rules(), now_iso="2026-07-09T09:00:00+08:00")
    output = py_build_signals.build_output(canonical, sample_profile(), sample_signal_rules(), generated_at="2026-07-09T09:30:00+08:00")
    signal = output["signals"][0]

    assert signal["importance_score"] == 5
    assert signal["display_title"] == "AI 智能体：Agent workflow and context 记忆 upda…"
    assert signal["display_summary"] == "这条内容与「AI 智能体」相关：Agent workflow and context 记忆 update."


def test_python_fetch_parser_handles_rss_and_atom():
    rss_items, rss_meta = parse_feed(
        """
        <rss><channel><title>Feed</title><item><guid>g1</guid><title>Title</title><link>https://example.com</link><description>Summary</description></item></channel></rss>
        """,
        "demo",
        10,
    )
    atom_items, atom_meta = parse_feed(
        """
        <feed xmlns="http://www.w3.org/2005/Atom"><title>Atom</title><entry><id>a1</id><title>Atom Title</title><link href="https://example.com/a" /></entry></feed>
        """,
        "demo",
        10,
    )

    assert rss_meta["format"] == "rss"
    assert rss_items[0]["raw_id"].startswith("rss:demo:")
    assert rss_items[0]["title"] == "Title"
    assert atom_meta["format"] == "atom"
    assert atom_items[0]["link"] == "https://example.com/a"


def test_python_runner_succeeded_empty_without_rss_sources(tmp_path):
    write_yaml(tmp_path / "config/sources.yml", {"version": 1, "sources": []})
    write_yaml(tmp_path / "config/ingestion-rules.yml", sample_ingestion_rules())
    write_yaml(tmp_path / "config/user-profile.yml", sample_profile())
    write_yaml(tmp_path / "config/signal-rules.yml", sample_signal_rules())

    status = PipelineRunner(root=tmp_path, timeout_seconds=5).refresh()

    assert status["status"] == "succeeded_empty"
    assert read_json(tmp_path / "data/signals/latest.json")["summary"]["signals"] == 0
    assert read_json(tmp_path / "data/app/refresh-status.json")["status"] == "succeeded_empty"


def test_python_runner_reports_failed_sources_without_failing_other_sources(monkeypatch, tmp_path):
    write_yaml(tmp_path / "config/sources.yml", sample_sources())
    write_yaml(tmp_path / "config/ingestion-rules.yml", sample_ingestion_rules())
    write_yaml(tmp_path / "config/user-profile.yml", sample_profile())
    write_yaml(tmp_path / "config/signal-rules.yml", sample_signal_rules())
    adapter_output = sample_adapter_output()
    adapter_output["results"].append(
        {
            "source_id": "github-trending-daily",
            "source_type": "rss",
            "provider": "github",
            "fetched_at": "2026-07-09T08:00:00+08:00",
            "status": "failed",
            "items": [],
            "errors": [
                {
                    "code": "rss_url_unreachable",
                    "message": "HTTP Error 503; GITHUB_ACCESS_TOKEN=secret-value",
                    "retryable": True,
                    "item_scope": "source",
                }
            ],
        }
    )
    monkeypatch.setattr("agentic_core.pipeline.runner.fetch_rss.fetch", lambda *_args: adapter_output)

    status = PipelineRunner(root=tmp_path, timeout_seconds=5).refresh()

    assert status["status"] == "succeeded_partial"
    assert status["adapter_summary"]["ok_sources"] == 1
    assert status["adapter_summary"]["failed_sources"] == 1
    failure = status["adapter_summary"]["source_results"][1]
    assert failure["source_id"] == "github-trending-daily"
    assert failure["errors"][0]["message"] == "HTTP Error 503; [REDACTED]"


def test_python_runner_failure_preserves_previous_successful_signals(tmp_path):
    write_json(tmp_path / "data/signals/latest.json", {"input_run_id": "old", "signals": []})

    status = PipelineRunner(root=tmp_path, timeout_seconds=5).refresh()

    assert status["status"] == "failed"
    assert read_json(tmp_path / "data/signals/latest.json")["input_run_id"] == "old"


def test_python_runner_module_cli_outputs_refresh_status(tmp_path):
    write_yaml(tmp_path / "config/sources.yml", {"version": 1, "sources": []})
    write_yaml(tmp_path / "config/ingestion-rules.yml", sample_ingestion_rules())
    write_yaml(tmp_path / "config/user-profile.yml", sample_profile())
    write_yaml(tmp_path / "config/signal-rules.yml", sample_signal_rules())

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "agentic_core.pipeline.runner",
            "--root",
            str(tmp_path),
            "--timeout-seconds",
            "5",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src/agentic-core")},
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout)["status"] == "succeeded_empty"
