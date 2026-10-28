"""디자인 테마: 브랜드 색 하나로 전체 색 맞추기, 레퍼런스 페이지에서 색·폰트·분위기 가져오기."""

from __future__ import annotations

import colorsys
import re
from pathlib import Path

from .. import config
from .claude import Writer
from .schema import Theme

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
FONTS = {"gothic": "고딕 (깔끔·신뢰)", "serif": "명조 (고급·차분)"}


def _rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))


def _hex(r: float, g: float, b: float) -> str:
    return "#" + "".join(f"{round(max(0, min(1, c)) * 255):02X}" for c in (r, g, b))


def _with_lightness(hex_color: str, lightness: float, saturation_scale: float = 1.0) -> str:
    h, _, s = colorsys.rgb_to_hls(*_rgb(hex_color))
    return _hex(*colorsys.hls_to_rgb(h, lightness, s * saturation_scale))


def luminance(hex_color: str) -> float:
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def on_color(hex_color: str) -> str:
    """이 배경 위에 올릴 글자색 (흰색 또는 거의 검정)."""
    return "#FFFFFF" if luminance(hex_color) < 0.45 else "#17191C"


def from_brand_color(primary: str, font: str = "gothic", radius: int = 20) -> Theme:
    """브랜드 메인 색 하나로 나머지 색을 만듭니다."""
    if not _HEX.match(primary):
        raise ValueError(f"색상은 #RRGGBB 형식이어야 합니다: {primary}")
    primary = primary.upper()
    return Theme(
        primary=primary,
        accent=_with_lightness(primary, 0.28),
        background="#FFFFFF",
        surface=_with_lightness(primary, 0.965, 0.6),
        text="#17191C",
        muted="#5F6670",
        font=font if font in FONTS else "gothic",
        radius=radius,
        mood="브랜드 색 기반",
    )


DEFAULT_THEME = from_brand_color("#2F6B5E")  # 차분한 청록 — 복지용구에 흔한 신뢰감 있는 색


def sanitize(theme: Theme) -> Theme:
    """AI가 준 값이 이상하면 기본값으로."""
    base = from_brand_color(theme.primary) if _HEX.match(theme.primary) else DEFAULT_THEME
    data = theme.model_dump()
    for key in ("primary", "accent", "background", "surface", "text", "muted"):
        if not _HEX.match(str(data[key])):
            data[key] = getattr(base, key)
    data["font"] = data["font"] if data["font"] in FONTS else "gothic"
    data["radius"] = max(0, min(40, int(data["radius"])))
    return Theme(**data)


def from_reference(client: Writer, images: list[Path]) -> Theme:
    """마음에 드는 상세페이지 캡처에서 색·폰트·분위기를 가져옵니다."""
    prompt = """첨부한 상세페이지(레퍼런스)의 디자인을 분석해 테마로 정리하세요.
- primary: 제목 강조·버튼에 쓰인 대표 색, accent: 더 진한 보조 색
- background: 페이지 기본 배경, surface: 카드·구분 배경, text: 본문 글자색, muted: 보조 글자색 (모두 #RRGGBB)
- font: 제목 글꼴이 고딕 계열이면 'gothic', 명조 계열이면 'serif'
- radius: 카드·이미지 모서리 둥글기(px, 0~40)
- mood: 분위기를 한국어 한 줄로"""
    return sanitize(client.json(prompt, Theme, files=images))


def load_global() -> Theme:
    if config.THEME_PATH.exists():
        return Theme.model_validate_json(config.THEME_PATH.read_text(encoding="utf-8"))
    return DEFAULT_THEME


def save(theme: Theme, path: Path | None = None) -> None:
    path = path or config.THEME_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(theme.model_dump_json(indent=2), encoding="utf-8")
