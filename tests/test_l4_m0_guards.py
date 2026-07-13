import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
L4_FIXTURES = ROOT / "tests" / "fixtures" / "l4"


def test_current_sources_match_m0_semantic_snapshot():
    current = yaml.safe_load((ROOT / "config" / "sources.yml").read_text(encoding="utf-8"))
    snapshot = json.loads(
        (L4_FIXTURES / "sources-semantic.json").read_text(encoding="utf-8")
    )

    assert current == snapshot


def test_l4_fixtures_are_synthetic_and_linked():
    events = json.loads(
        (L4_FIXTURES / "user-context-events.json").read_text(encoding="utf-8")
    )
    profile = json.loads(
        (L4_FIXTURES / "profile-snapshot.json").read_text(encoding="utf-8")
    )
    canonical = json.loads(
        (L4_FIXTURES / "canonical-items.json").read_text(encoding="utf-8")
    )
    signals = json.loads((L4_FIXTURES / "signals.json").read_text(encoding="utf-8"))

    event_ids = {event["event_id"] for event in events["events"]}
    item_ids = {item["id"] for item in canonical["items"]}

    assert profile["user_id"] == "fixture-user"
    assert set(profile["based_on_event_ids"]) <= event_ids
    assert signals["input_run_id"] == canonical["run_id"]
    assert signals["profile_id"] == profile["profile_id"]
    assert {signal["id"] for signal in signals["signals"]} <= item_ids
    serialized = json.dumps([events, profile, canonical, signals], ensure_ascii=False)
    assert "sk-" not in serialized
    assert "ghp_" not in serialized
    assert "access_token=" not in serialized.lower()
