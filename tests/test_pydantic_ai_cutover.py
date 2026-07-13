import inspect
from pathlib import Path

from agentic_core.core import AgenticCore
from agentic_core.runtime.pydantic_ai_runtime import PydanticAIRuntime


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "agentic-core" / "agentic_core"


def test_agentic_core_constructor_has_no_legacy_provider_injection():
    parameters = inspect.signature(AgenticCore).parameters

    assert list(parameters) == ["config", "tools", "runtime"]


def test_self_built_provider_package_and_tests_are_deleted():
    assert not (PACKAGE_ROOT / "providers").exists()
    assert not (ROOT / "tests" / "test_provider.py").exists()


def test_self_built_loop_symbols_are_absent_from_runtime_source():
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in PACKAGE_ROOT.rglob("*.py")
    )

    assert "ProviderResponse" not in source
    assert "ProviderToolCall" not in source
    assert "OpenAICompatibleProvider" not in source
    assert "build_provider" not in source
    assert "for _turn in range" not in source


def test_agentic_core_source_constructs_pydantic_runtime_as_only_default():
    source = inspect.getsource(AgenticCore.__init__)

    assert "PydanticAIRuntime" in source
    assert "runtime or PydanticAIRuntime" in source
