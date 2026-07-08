from agentic_core.run import parse_args


def test_parse_args_defaults():
    args = parse_args(["--prompt", "hello"])

    assert args.config == "config/agentic-core.yml"
    assert args.prompt == "hello"


def test_parse_args_accepts_config():
    args = parse_args(["--config", "config/agentic-core.example.yml", "--prompt", "hello"])

    assert args.config == "config/agentic-core.example.yml"
    assert args.prompt == "hello"
