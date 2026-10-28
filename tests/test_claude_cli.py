"""터미널 Claude Code(`claude -p`) 방식 — 가짜 claude 명령으로 확인."""

import json
import stat
import sys

import pytest
from fakes import SAMPLE_FACTS, FakeClaude, FakePainter

from nstore.detail import claude
from nstore.detail.claude import ClaudeCodeClient, ClaudeError, ClaudeLimitError
from nstore.detail.schema import ReviewInsights

FAKE_CLAUDE = f"""#!{sys.executable}
import json, os, sys
with open(os.environ["FAKE_CLAUDE_LOG"], "w", encoding="utf-8") as f:
    json.dump({{"args": sys.argv[1:], "prompt": sys.stdin.read(),
               "api_key_passed": "ANTHROPIC_API_KEY" in os.environ}}, f, ensure_ascii=False)
print(os.environ["FAKE_CLAUDE_OUT"])
"""


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    exe = tmp_path / "claude"
    exe.write_text(FAKE_CLAUDE, encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "log.json"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-be-used")

    def run(result: dict, **json_kwargs):
        monkeypatch.setenv("FAKE_CLAUDE_OUT", json.dumps(result, ensure_ascii=False))
        client = ClaudeCodeClient("claude-opus-5-5", "high", cli_path=str(exe))
        value = client.json(**({"prompt": "정리해줘", "schema": ReviewInsights} | json_kwargs))
        return value, json.loads(log.read_text(encoding="utf-8"))

    return run


OK = {"type": "result", "subtype": "success", "is_error": False, "result": "",
      "structured_output": {"selling_points": ["가벼워요"], "complaints": [], "questions": []}}


def test_cli_request_and_result(fake_cli, tmp_path):
    photo = tmp_path / "photos" / "front.jpg"
    photo.parent.mkdir()
    photo.write_bytes(b"x")
    value, call = fake_cli(OK, files=[photo], system="원칙")

    assert value.selling_points == ["가벼워요"]
    args = call["args"]
    assert args[0] == "-p" and args[args.index("--output-format") + 1] == "json"
    assert args[args.index("--model") + 1] == "claude-opus-5-5" and args[args.index("--effort") + 1] == "high"
    assert args[args.index("--tools") + 1] == "Read"                 # 읽기만 허용
    assert args[args.index("--add-dir") + 1] == str(photo.parent.resolve())
    assert args[args.index("--system-prompt") + 1] == "원칙"
    schema = json.loads(args[args.index("--json-schema") + 1])
    assert schema["additionalProperties"] is False and "selling_points" in schema["required"]
    assert str(photo.resolve()) in call["prompt"] and call["prompt"].endswith("정리해줘")
    assert call["api_key_passed"] is False                            # 구독 로그인으로 돌게 API 키는 넘기지 않음


def test_cli_falls_back_to_result_text(fake_cli):
    text = json.dumps({"selling_points": [], "complaints": ["소음"], "questions": []}, ensure_ascii=False)
    value, _ = fake_cli({"type": "result", "subtype": "success", "is_error": False, "result": text})
    assert value.complaints == ["소음"]


def test_cli_errors(fake_cli):
    with pytest.raises(ClaudeLimitError):
        fake_cli({"subtype": "success", "is_error": True, "result": "Claude usage limit reached · resets 3pm"})
    with pytest.raises(ClaudeError, match="로그인"):
        fake_cli({"subtype": "success", "is_error": True, "result": "Not logged in · Please run /login"})


def test_missing_cli():
    with pytest.raises(ClaudeError, match="claude"):
        ClaudeCodeClient("m", "high", cli_path="/없는/경로/claude").json("x", ReviewInsights)


def test_make_writer_backend(monkeypatch):
    base = {"model": "claude-opus-5-5", "effort": "high"}
    monkeypatch.setattr(claude, "load_yaml", lambda _: {"claude": base | {"backend": "cli"}})
    assert isinstance(claude.make_writer(), ClaudeCodeClient)
    monkeypatch.setattr(claude, "load_yaml", lambda _: {"claude": base | {"backend": "api"}})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert isinstance(claude.make_writer(), claude.ClaudeClient)


def test_batch_resumes_and_stops_at_limit(tmp_path, monkeypatch, capsys):
    from fakes import png_bytes

    from nstore import __main__ as cli
    from nstore import config
    from nstore.detail import gemini, service
    from nstore.detail.schema import Facts
    from nstore.detail.workspace import Workspace

    monkeypatch.setattr(config, "PRODUCTS_DIR", tmp_path / "products")
    monkeypatch.setattr(config, "MASTER_PATH", tmp_path / "master.xlsx")
    for code in ("A1", "A2", "A3"):
        ws = Workspace(code).ensure()
        (ws.photos_dir / "front.jpg").write_bytes(png_bytes())
    Workspace("A1").save_facts(Facts.model_validate(SAMPLE_FACTS))   # A1 은 자료 정리가 이미 끝남

    writer = FakeClaude()
    calls = {"n": 0}
    original = writer.json

    def limited(prompt, schema, files=(), system=None):
        calls["n"] += 1
        if calls["n"] > 6:
            raise ClaudeLimitError("사용 한도")
        return original(prompt, schema, files, system)

    writer.json = limited
    monkeypatch.setattr(claude, "make_writer", lambda: writer)
    monkeypatch.setattr(gemini.GeminiClient, "from_env", classmethod(lambda cls: FakePainter()))
    monkeypatch.setattr(service, "run_export", lambda *a, **k: ["내보내기"])

    assert cli.main(["detail", "all", "--all"]) == 1
    err = capsys.readouterr().err
    assert "[멈춤]" in err and "남은 상품" in err
    schemas = [c[1].__name__ for c in writer.json_calls]
    assert schemas[:3] == ["Plan", "ImagePrompt", "ImagePrompt"]       # A1: 자료 정리 건너뛰고 구성부터
    assert Workspace("A2").load_facts() is not None                    # A2 는 진행하다 한도에서 멈춤
