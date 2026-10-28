"""Claude 연결: 자료 분석, 기획·카피, 이미지 프롬프트 작성.

두 가지 방식 중 config/settings.yaml 의 claude.backend 로 고릅니다.
- cli : 터미널의 Claude Code(`claude -p`)를 부릅니다. Claude 구독 로그인으로 돌아가고 API 키가 필요 없습니다.
- api : Anthropic API(ANTHROPIC_API_KEY)로 직접 부릅니다.

어느 쪽이든 정해진 구조(pydantic 모델)의 JSON으로 받습니다(구조화 출력).
"""

from __future__ import annotations

import base64
import io
import json
import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, TypeVar

from PIL import Image
from pydantic import BaseModel, ValidationError

from .. import config
from ..config import load_yaml

T = TypeVar("T", bound=BaseModel)

INLINE_PDF_LIMIT = 20 * 1024 * 1024  # 이보다 큰 PDF는 Files API로 올려서 참조 (요청 한 번 최대 32MB)
IMAGE_MAX_EDGE = 1568  # 이보다 큰 사진은 줄여서 보냄 (휴대폰 원본은 장당 5MB 제한을 넘기 쉬움)
# 안전 분류기가 요청을 거절하면 서버가 알아서 다른 모델로 다시 돌리게 함
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeError(RuntimeError):
    pass


class ClaudeLimitError(ClaudeError):
    """구독 사용 한도에 걸림 — 일괄 처리는 여기서 멈추고 나중에 이어서 합니다."""


class Writer(Protocol):
    def json(self, prompt: str, schema: type[T], files: Sequence[Path] = (), system: str | None = None) -> T: ...


def make_writer() -> Writer:
    cfg = load_yaml("settings.yaml")["claude"]
    if cfg.get("backend", "cli") == "api":
        return ClaudeClient(cfg["model"], cfg["effort"])
    return ClaudeCodeClient(cfg["model"], cfg["effort"], cfg.get("cli_path") or None, cfg.get("cli_timeout_minutes", 20))


def _b64(data: bytes) -> str:
    return base64.standard_b64encode(data).decode()


def _jpeg_block(im: Image.Image) -> dict:
    im = im.copy()
    im.thumbnail((IMAGE_MAX_EDGE, IMAGE_MAX_EDGE), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _b64(buf.getvalue())}}


def image_blocks(path: Path, max_slices: int = 5) -> list[dict]:
    """사진 → 이미지 블록. 상세페이지 캡처처럼 아주 긴 이미지는 줄이면 글자가 안 보이니 위에서부터 잘라서 보냄."""
    with Image.open(path) as im:
        im = im.convert("RGB")
        if im.height <= im.width * 2.5:
            return [_jpeg_block(im)]
        step = int(im.width * 1.5)
        tops = range(0, im.height, step)[:max_slices]
        return [_jpeg_block(im.crop((0, top, im.width, min(im.height, top + step)))) for top in tops]


# ---------------------------------------------------------------- Anthropic API


class ClaudeClient:
    """Anthropic API로 직접 부릅니다 (backend: api). ANTHROPIC_API_KEY 필요."""

    def __init__(self, model: str, effort: str, client=None):
        import anthropic

        # 키는 .env 의 ANTHROPIC_API_KEY (또는 'ant auth login' 으로 저장한 로그인)
        self._client = client or anthropic.Anthropic()
        self.model = model
        self.effort = effort

    def _blocks(self, path: Path) -> list[dict]:
        """파일 하나 → 메시지 블록. 사진은 파일 이름을 먼저 적어 Claude가 이름으로 가리킬 수 있게."""
        if path.suffix.lower() == ".pdf":
            data = path.read_bytes()
            if len(data) > INLINE_PDF_LIMIT:
                source = {"type": "file", "file_id": self._client.files.upload(file=path).id}
            else:
                source = {"type": "base64", "media_type": "application/pdf", "data": _b64(data)}
            return [{"type": "document", "source": source, "title": path.name}]
        if path.suffix.lower() in (".txt", ".md"):
            return [{"type": "text", "text": f"[자료: {path.name}]\n{path.read_text(encoding='utf-8')}"}]
        return [{"type": "text", "text": f"[사진: {path.name}]"}, *image_blocks(path)]

    def json(self, prompt: str, schema: type[T], files: Sequence[Path] = (), system: str | None = None) -> T:
        import anthropic

        content = [block for f in files for block in self._blocks(f)]
        content.append({"type": "text", "text": prompt})
        try:
            with self._client.beta.messages.stream(
                model=self.model,
                max_tokens=64000,
                betas=[FALLBACK_BETA],
                fallbacks="default",
                output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": anthropic.transform_schema(schema)}},
                messages=[{"role": "user", "content": content}],
                **({"system": system} if system else {}),
            ) as stream:
                message = stream.get_final_message()
        except anthropic.AuthenticationError as e:
            raise ClaudeError("Claude API 키가 없거나 맞지 않습니다. .env 의 ANTHROPIC_API_KEY 를 확인하세요.") from e
        except anthropic.NotFoundError as e:
            raise ClaudeError(f"Claude 모델 '{self.model}'을(를) 찾을 수 없습니다. config/settings.yaml 의 claude.model 을 확인하세요.") from e
        except anthropic.RateLimitError as e:
            raise ClaudeError("Claude 요청이 몰려 잠시 막혔습니다. 조금 뒤 다시 시도하세요.") from e
        except anthropic.APIStatusError as e:
            raise ClaudeError(f"Claude 호출 실패 ({e.status_code}): {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise ClaudeError("Claude에 연결하지 못했습니다. 인터넷 연결을 확인하세요.") from e
        except anthropic.AnthropicError as e:  # 키가 아예 설정되지 않은 경우 등
            raise ClaudeError(f"Claude 설정 오류: {e}. .env 의 ANTHROPIC_API_KEY 를 확인하세요.") from e

        if message.stop_reason == "refusal":
            raise ClaudeError("Claude가 이 요청을 거절했습니다. 자료나 요청 문구를 바꿔 다시 시도하세요.")
        if message.stop_reason == "max_tokens":
            raise ClaudeError("응답이 너무 길어 중간에 잘렸습니다. 자료를 나누거나 요청을 줄여 다시 시도하세요.")
        text = next((b.text for b in message.content if b.type == "text"), "")
        try:
            return schema.model_validate_json(text)
        except ValueError as e:
            raise ClaudeError(f"Claude 응답을 정해진 형식으로 읽지 못했습니다: {text[:200]}") from e


# ---------------------------------------------------------------- 터미널의 Claude Code


def _schema(model: type[BaseModel]) -> dict:
    """API 구조화 출력과 같은 규칙으로 정리한 JSON 스키마."""
    import anthropic

    return anthropic.transform_schema(model)


class ClaudeCodeClient:
    """`claude -p` (Claude Code 비대화 모드)로 부릅니다. 사진·PDF는 Claude Code가 Read 도구로 직접 읽습니다."""

    # 이 환경변수가 있으면 Claude Code가 구독 로그인 대신 API 키로 과금하므로 넘기지 않음.
    # CLAUDECODE 는 Claude Code 안에서 이 프로그램을 돌릴 때 중첩 실행으로 막히지 않게 뺌.
    DROP_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDECODE")

    def __init__(self, model: str, effort: str, cli_path: str | None = None, timeout_minutes: float = 20):
        self.model = model
        self.effort = effort
        self.cli_path = cli_path
        self.timeout = timeout_minutes * 60

    def _binary(self) -> str:
        path = self.cli_path or shutil.which("claude")
        if not path or not Path(path).exists():
            raise ClaudeError(
                "터미널에서 'claude' 명령을 찾지 못했습니다. Claude Code를 설치하고 터미널에서 'claude' 를 한 번 실행해 "
                "로그인하세요. 다른 위치에 설치했다면 config/settings.yaml 의 claude.cli_path 에 경로를 적으세요."
            )
        return path

    def json(self, prompt: str, schema: type[T], files: Sequence[Path] = (), system: str | None = None) -> T:
        paths = [Path(f).resolve() for f in files]
        if paths:
            listing = "\n".join(f"- {p}" for p in paths)
            prompt = ("먼저 Read 도구로 아래 파일을 모두 끝까지 읽으세요. 10쪽이 넘는 PDF는 pages 로 나눠 전부 읽으세요. "
                      f"사진은 파일 이름으로 가리키세요.\n{listing}\n\n{prompt}")

        cmd = [
            self._binary(), "-p",
            "--output-format", "json",
            "--json-schema", json.dumps(_schema(schema), ensure_ascii=False),
            "--model", self.model,
            "--effort", self.effort,
            "--tools", "Read",  # 파일 읽기만 허용 (명령 실행·파일 수정 불가)
            "--allowedTools", "Read",
            "--no-session-persistence",
        ]
        for folder in sorted({str(p.parent) for p in paths}):
            cmd += ["--add-dir", folder]
        if system:
            cmd += ["--system-prompt", system]

        env = {k: v for k, v in os.environ.items() if k not in self.DROP_ENV}
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, env=env,
                                  cwd=config.ROOT, timeout=self.timeout)
        except subprocess.TimeoutExpired as e:
            raise ClaudeError(f"Claude Code가 {self.timeout / 60:.0f}분 안에 끝내지 못했습니다. "
                              "claude.cli_timeout_minutes 를 늘리거나 자료를 나눠 보세요.") from e

        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            detail = (proc.stderr or proc.stdout).strip()[:300]
            raise ClaudeError(f"Claude Code 실행 실패: {detail or '응답 없음'}") from e

        message = str(out.get("result", ""))
        if out.get("is_error") or out.get("subtype") != "success":
            if "limit" in message.lower():
                raise ClaudeLimitError(f"Claude 사용 한도에 걸렸습니다. 한도가 풀린 뒤 다시 실행하세요. ({message[:200]})")
            if "login" in message.lower() or "api key" in message.lower():
                raise ClaudeError(f"Claude Code 로그인이 필요합니다. 터미널에서 'claude' 를 실행해 로그인하세요. ({message[:200]})")
            raise ClaudeError(f"Claude Code 오류: {message[:300] or out.get('subtype')}")

        data = out.get("structured_output")
        try:
            return schema.model_validate(data) if data is not None else schema.model_validate_json(message)
        except ValidationError as e:
            raise ClaudeError(f"Claude Code 응답을 정해진 형식으로 읽지 못했습니다: {message[:200]}") from e
