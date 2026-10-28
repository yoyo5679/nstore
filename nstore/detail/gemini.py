"""Gemini API 연결. 글(구조화 JSON)과 이미지 두 가지만 씁니다."""

from __future__ import annotations

import mimetypes
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from ..config import load_yaml, require_env

T = TypeVar("T", bound=BaseModel)
INLINE_LIMIT = 15 * 1024 * 1024  # 이보다 큰 파일(두꺼운 카탈로그 PDF)은 업로드 후 참조
RETRY_CODES = {429, 500, 503}


class GeminiError(RuntimeError):
    pass


class GeminiClient:
    def __init__(self, api_key: str, text_model: str, image_model: str):
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self.text_model = text_model
        self.image_model = image_model

    @classmethod
    def from_env(cls) -> "GeminiClient":
        cfg = load_yaml("settings.yaml")["gemini"]
        return cls(require_env("GEMINI_API_KEY"), cfg["text_model"], cfg["image_model"])

    def _part(self, path: Path):
        from google.genai import types

        data = path.read_bytes()
        if len(data) > INLINE_LIMIT:
            return self._client.files.upload(file=path)
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return types.Part.from_bytes(data=data, mime_type=mime)

    def _call(self, model: str, contents: list, config):
        from google.genai import errors

        delay = 2.0
        for attempt in range(4):
            try:
                return self._client.models.generate_content(model=model, contents=contents, config=config)
            except errors.APIError as e:
                if e.code == 404:
                    raise GeminiError(
                        f"모델 '{model}'을(를) 찾을 수 없습니다. 화면의 '사용 가능한 모델 확인'으로 이름을 확인하고 "
                        "config/settings.yaml 의 gemini 항목을 고치세요."
                    ) from e
                if e.code not in RETRY_CODES or attempt == 3:
                    raise GeminiError(f"Gemini 호출 실패 ({e.code}): {e.message}") from e
                time.sleep(delay)
                delay *= 2

    def json(self, prompt: str, schema: type[T], files: Sequence[Path] = (), system: str | None = None) -> T:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
        )
        resp = self._call(self.text_model, [*(self._part(f) for f in files), prompt], config)
        if isinstance(resp.parsed, schema):
            return resp.parsed
        try:
            return schema.model_validate_json(resp.text or "")
        except ValueError as e:
            raise GeminiError(f"Gemini 응답을 읽지 못했습니다: {(resp.text or '')[:300]}") from e

    def image(self, prompt: str, references: Sequence[Path] = (), aspect_ratio: str | None = None) -> bytes:
        from google.genai import types

        config = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=aspect_ratio) if aspect_ratio else None,
        )
        resp = self._call(self.image_model, [*(self._part(f) for f in references), prompt], config)
        for part in resp.parts or []:
            if part.inline_data and part.inline_data.data:
                return part.inline_data.data
        reason = resp.prompt_feedback.block_reason if resp.prompt_feedback else ""
        raise GeminiError(f"이미지가 만들어지지 않았습니다. {reason or (resp.text or '')[:200]}")

    def list_models(self) -> list[str]:
        return sorted(m.name.removeprefix("models/") for m in self._client.models.list())
