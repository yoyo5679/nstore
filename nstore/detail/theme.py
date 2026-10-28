"""디자인 테마: 브랜드 색 하나로 전체 색 맞추기, 레퍼런스에서 색·글꼴·배치·기획 방식 가져오기."""

from __future__ import annotations

import colorsys
import re
from pathlib import Path

from .. import config
from .claude import Writer
from .schema import LAYOUT_OPTIONS, SECTION_TYPES, ReferenceAnalysis, ReferenceGuide, Theme

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


def from_brand_color(primary: str, font: str = "gothic", radius: int = 20, layout: dict | None = None) -> Theme:
    """브랜드 메인 색 하나로 나머지 색을 만듭니다. layout 은 정렬·첫 화면·사진·배경 배치."""
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
        **{k: v for k, v in (layout or {}).items() if v in LAYOUT_OPTIONS.get(k, {})},
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
    for key, options in LAYOUT_OPTIONS.items():
        if data[key] not in options:
            data[key] = next(iter(options))
    return Theme(**data)


REFERENCE_PROMPT = """첨부한 상세페이지(레퍼런스) 캡처를 보고, 우리 상세페이지를 비슷한 느낌으로 만들 수 있게 디자인과 기획 방식을 정리하세요.
레퍼런스의 문장·사진·로고를 가져오려는 것이 아니라 스타일만 따라 하려는 것입니다.

디자인
- primary: 제목 강조·버튼에 쓰인 대표 색, accent: 더 진한 보조 색
- background: 기본 배경, surface: 카드·구분 배경, text: 본문 글자색, muted: 보조 글자색 (모두 #RRGGBB)
- font: 제목 글꼴이 고딕 계열이면 gothic, 명조 계열이면 serif
- radius: 카드·사진 모서리 둥글기 (px, 0~40)
- align: 글이 주로 가운데 정렬이면 center, 왼쪽 정렬이면 left
- hero: 첫 화면이 사진 위에 글을 얹은 형태면 overlay, 글과 사진이 위아래로 나뉘면 stacked
- image_style: 사진이 화면 양옆 끝까지 꽉 차면 full, 여백 안에 둥근 모서리 사진이면 rounded
- sections: 섹션마다 배경색이 번갈아 바뀌면 alternate, 거의 한 배경이면 plain
- mood: 분위기를 한국어 한 줄로

기획
- section_flow: 레퍼런스의 섹션 흐름을 위에서부터 다음 이름으로 적으세요 — hero(첫 화면), problem(고민 공감),
  solution(해결 제시), feature(특징), trust(신뢰·인증·후기), usage(사용법), faq(자주 묻는 질문), spec(제품 정보),
  caution(주의사항), cta(마무리)
- copy_tone: 말투(존댓말·반말), 문장 길이, 헤드라인 방식(질문형·숫자 강조 등)
- photo_style: 사진 분위기 (조명, 배경 장소, 사람이 나오는지, 색감, 구도)
- notes: 그 밖에 따라 하면 좋은 점 3~5개"""


def analyze_reference(client: Writer, files: list[Path]) -> tuple[Theme, ReferenceGuide]:
    """마음에 드는 상세페이지(캡처 이미지·링크 캡처)에서 디자인과 기획 방식을 가져옵니다."""
    a = client.json(REFERENCE_PROMPT, ReferenceAnalysis, files=files)
    theme = sanitize(Theme(**{k: getattr(a, k) for k in Theme.model_fields}))
    guide = ReferenceGuide(
        section_flow=[t for t in a.section_flow if t in SECTION_TYPES],
        copy_tone=a.copy_tone,
        photo_style=a.photo_style,
        notes=a.notes,
    )
    return theme, guide


def save_reference(guide: ReferenceGuide | None, path: Path | None = None) -> None:
    """레퍼런스 기획 방식 저장. None 이면 지웁니다."""
    path = path or config.REFERENCE_PATH
    if guide is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(guide.model_dump_json(indent=2), encoding="utf-8")


def load_global() -> Theme:
    if config.THEME_PATH.exists():
        return Theme.model_validate_json(config.THEME_PATH.read_text(encoding="utf-8"))
    return DEFAULT_THEME


def save(theme: Theme, path: Path | None = None) -> None:
    path = path or config.THEME_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(theme.model_dump_json(indent=2), encoding="utf-8")
