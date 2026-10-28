"""Claude 연결: 자료 분석, 기획·카피, 이미지 프롬프트 작성.

모든 요청은 정해진 구조(pydantic 모델)의 JSON으로 받습니다(구조화 출력).
거절·중간 잘림을 먼저 확인한 뒤 직접 읽기 위해 SDK의 자동 파싱(output_format) 대신 스키마를 output_config 로 넘깁니다.
"""

from __future__ import annotations

import base64
import io
from collections.abc import Sequence
from pathlib import Path
from typing import TypeVar

from PIL import Image
from pydantic import BaseModel

from ..config import load_yaml

T = TypeVar("T", bound=BaseModel)

INLINE_PDF_LIMIT = 20 * 1024 * 1024  # 이보다 큰 PDF는 Files API로 올려서 참조 (요청 한 번 최대 32MB)
IMAGE_MAX_EDGE = 1568  # 이보다 큰 사진은 줄여서 보냄 (휴대폰 원본은 장당 5MB 제한을 넘기 쉬움)
# 안전 분류기가 요청을 거절하면 서버가 알아서 다른 모델로 다시 돌리게 함
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeError(RuntimeError):
    pass


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


class ClaudeClient:
    def __init__(self, model: str, effort: str, client=None):
        import anthropic

        # 키는 .env 의 ANTHROPIC_API_KEY (또는 'ant auth login' 으로 저장한 로그인)
        self._client = client or anthropic.Anthropic()
        self.model = model
        self.effort = effort

    @classmethod
    def from_env(cls) -> "ClaudeClient":
        cfg = load_yaml("settings.yaml")["claude"]
        return cls(cfg["model"], cfg["effort"])

    def _blocks(self, path: Path) -> list[dict]:
        """파일 하나 → 메시지 블록. 사진은 파일 이름을 먼저 적어 Claude가 이름으로 가리킬 수 있게."""
        if path.suffix.lower() == ".pdf":
            data = path.read_bytes()
            if len(data) > INLINE_PDF_LIMIT:
                source = {"type": "file", "file_id": self._client.files.upload(file=path).id}
            else:
                source = {"type": "base64", "media_type": "application/pdf", "data": _b64(data)}
            return [{"type": "document", "source": source, "title": path.name}]
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
