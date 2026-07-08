from typing import Any

ALLOWED_ROLES = {"system", "user", "assistant", "tool"}


def normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        role = str(message.get("role", "")).strip()
        if role not in ALLOWED_ROLES:
            raise ValueError(f"unsupported message role at index {index}: {role}")

        content = message.get("content", "")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"message content must not be empty at index {index}")

        normalized.append({"role": role, "content": content.strip()})
    return normalized
