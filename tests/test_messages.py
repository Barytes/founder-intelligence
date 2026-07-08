import pytest

from agentic_core.messages import normalize_messages


def test_normalize_messages_accepts_role_content_dicts():
    messages = normalize_messages([{"role": "user", "content": "hello"}])

    assert messages == [{"role": "user", "content": "hello"}]


def test_normalize_messages_rejects_unknown_role():
    with pytest.raises(ValueError, match="unsupported message role"):
        normalize_messages([{"role": "admin", "content": "hello"}])


def test_normalize_messages_rejects_empty_content():
    with pytest.raises(ValueError, match="message content must not be empty"):
        normalize_messages([{"role": "user", "content": "   "}])
