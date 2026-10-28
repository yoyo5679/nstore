"""Gemini API 연결 — 이미지 생성(Nano Banana)만 씁니다. 분석·글·이미지 프롬프트는 Claude(claude.py)가 맡습니다."""

from __future__ import annotations

import mimetypes
import time
from collections.abc import Sequence
from pathlib import Path

from ..config import load_yaml, require_env

INLINE_LIMIT = 15 * 1024 * 1024  # 이보다 큰 파일(두꺼운 카탈로그 PDF)은 업로드 후 참조
RETRY_CODES = {429, 500, 503}


class GeminiError(RuntimeError):
    pass


class GeminiClient:
    def __init__(self, api_key: str, image_model: str):
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self.image_model = image_model

    @classmethod
    def from_env(cls) -> "GeminiClient":
        cfg = load_yaml("settings.yaml")["gemini"]
        return cls(require_env("GEMINI_API_KEY"), cfg["image_model"])

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
