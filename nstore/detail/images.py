"""연출 컷 생성·배경 편집.

1. Claude가 실사진·섹션 카피·사실 자료를 보고 이미지 프롬프트(영어)를 씁니다.
2. Gemini 이미지 모델(Nano Banana)이 실사진을 참고 이미지로 받아 그립니다.

제품 모양이 바뀌지 않게 실사진을 함께 넣고, 이미지 안에 글자는 넣지 않습니다.
(글자·스펙은 HTML로 얹어서 오타·지어낸 숫자가 생기지 않게 합니다.)
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from .claude import Writer
from .gemini import GeminiClient
from .schema import SECTION_LABELS, ImagePrompt, Plan, Section
from .workspace import Workspace

PROMPT_SYSTEM = """당신은 한국 복지용구 상세페이지의 사진을 기획하는 아트디렉터입니다.
이미지 생성 AI(Google Gemini 이미지 모델)에 보낼 영어 프롬프트 한 문단을 씁니다. 첨부한 실사진은 참고 이미지로 함께 들어갑니다.

반드시 지킬 것:
- 제품은 참고 사진 속 제품과 똑같아야 합니다(모양, 비율, 색, 재질, 부품, 로고). 제품을 바꾸거나 부품을 더하지 말라고 프롬프트에 분명히 쓰세요.
- 이미지 안에 글자, 숫자, 로고, 워터마크, 말풍선을 넣지 말라고 쓰세요.
- 사람이 나오면 한국 사람, 한국 가정이나 동네를 배경으로 합니다. 어르신은 밝고 품위 있게 그리고, 아프거나 불쌍해 보이게 그리지 마세요.
- 사실 자료의 사용법·주의사항에 어긋나는 장면(잘못된 사용, 위험한 자세)은 만들지 마세요.
- 구도, 카메라 거리와 각도, 조명, 배경, 분위기를 구체적으로 쓰세요."""

KIND_GUIDE = {
    "scene": "사용 장면 — 제품을 실제로 쓰는 모습. 섹션이 말하려는 장점이 한눈에 보이게.",
    "detail": "디테일 컷 — 섹션이 말하는 부분을 가까이에서 선명하게. 깔끔한 배경, 부드러운 조명.",
    "cutout": "흰 배경 제품컷 — 순백(#FFFFFF) 배경 가운데 제품 전체, 자연스러운 그림자, 쇼핑몰 카탈로그 스타일.",
    "extend": "배경 확장 — 첫 번째 사진의 내용은 그대로 두고 바깥 배경만 자연스럽게 넓혀 새 비율을 채움.",
}

# Claude가 쓴 프롬프트 뒤에 항상 붙이는 안전장치
KEEP_PRODUCT = (
    "The product must look exactly like the product in the reference photos: same shape, proportions, "
    "colors, materials, parts and logo. Do not redesign, simplify or add parts. "
    "Do not add any text, letters, numbers, captions, logos or watermarks to the image. Photorealistic."
)


def write_prompt(
    writer: Writer,
    ws: Workspace,
    *,
    kind: str,
    scene: str,
    refs: list[Path],
    ratio: str,
    section: Section | None = None,
    instruction: str = "",
    editing: bool = False,
) -> str:
    """Claude가 실사진을 보고 Gemini에 보낼 프롬프트를 씁니다."""
    lines = [f"이미지 종류: {KIND_GUIDE[kind]}", f"화면 비율: {ratio}"]
    if section:
        lines.append(f"들어갈 섹션: {SECTION_LABELS.get(section.type, section.type)} — 헤드라인 '{section.headline}', 본문 '{section.body}'")
    if scene:
        lines.append(f"기획한 장면: {scene}")
    if editing:
        lines.append(f"첫 번째 사진은 지금 이미지입니다. 이 이미지를 고치는 편집 프롬프트를 쓰세요. "
                     f"다음 요청만 반영하고 나머지는 그대로 두라고 쓰세요: {instruction}")
    elif instruction:
        lines.append(f"추가 요청: {instruction}")
    facts = ws.load_facts()
    if facts:
        lines.append(f"제품: {facts.product_name} — {facts.one_line}")
        lines.append(f"사용법: {facts.usage_steps}")
        lines.append(f"주의사항: {facts.cautions}")
    lines.append("prompt 에 영어 프롬프트 한 문단만 적으세요.")
    result = writer.json("\n".join(lines), ImagePrompt, files=refs, system=PROMPT_SYSTEM)
    return f"{result.prompt.strip()} {KEEP_PRODUCT}"


def _references(ws: Workspace, section: Section, limit: int) -> list[Path]:
    photos = ws.photos()
    first = ws.photo(section.image.photo)
    if section.image.kind == "extend" and first:
        return [first]  # 배경 확장은 원본 한 장만
    ordered = ([first] if first else []) + [p for p in photos if p != first]
    return ordered[:limit]


def aspect_ratio(section: Section, settings: dict) -> str:
    ratios = settings["detail"]["aspect_ratios"]
    return ratios.get(section.type, ratios["default"])


def generate_section_image(
    ws: Workspace, writer: Writer, painter: GeminiClient, section: Section, settings: dict, instruction: str = ""
) -> Path:
    kind = section.image.kind if section.image.kind in KIND_GUIDE else "scene"
    if kind == "extend" and not ws.photo(section.image.photo):
        kind = "scene"
    refs = _references(ws, section, settings["gemini"]["max_reference_photos"])
    if not refs:
        raise ValueError("실사진(photos/)이 없어 제품 모양을 맞출 수 없습니다. 사진을 먼저 올리세요.")
    ratio = aspect_ratio(section, settings)
    prompt = write_prompt(writer, ws, kind=kind, scene=section.image.prompt, refs=refs, ratio=ratio,
                          section=section, instruction=instruction)
    path = ws.save_section_image(section.id, painter.image(prompt, refs, ratio))
    ws.save_image_prompt(section.id, prompt)
    return path


def edit_section_image(
    ws: Workspace, writer: Writer, painter: GeminiClient, section: Section, instruction: str, settings: dict
) -> Path:
    """지금 이미지를 바탕으로 말한 부분만 고칩니다."""
    current = ws.section_image(section.id) or ws.photo(section.image.photo)
    if current is None:
        return generate_section_image(ws, writer, painter, section, settings, instruction)
    refs = [current] + [p for p in ws.photos() if p != current][: settings["gemini"]["max_reference_photos"] - 1]
    ratio = aspect_ratio(section, settings)
    kind = section.image.kind if section.image.kind in KIND_GUIDE else "scene"
    prompt = write_prompt(writer, ws, kind=kind, scene=section.image.prompt, refs=refs, ratio=ratio,
                          section=section, instruction=instruction, editing=True)
    path = ws.save_section_image(section.id, painter.image(prompt, refs, ratio))
    ws.save_image_prompt(section.id, prompt)
    return path


def generate_missing(ws: Workspace, writer: Writer, painter: GeminiClient, plan: Plan, settings: dict, progress=None) -> list[str]:
    """아직 이미지가 없는 'generate' 섹션만 만듭니다."""
    targets = [s for s in plan.sections if s.image.mode == "generate" and not ws.section_image(s.id)]
    notes = []
    for n, section in enumerate(targets):
        if progress:
            progress(n / len(targets), f"이미지 생성 중 {n + 1}/{len(targets)} ({section.id})")
        generate_section_image(ws, writer, painter, section, settings)
        notes.append(f"{section.id} 이미지 생성")
    return notes or ["새로 만들 이미지가 없습니다."]


def make_thumbnail(ws: Workspace, writer: Writer, painter: GeminiClient, settings: dict) -> Path:
    """대표이미지용 흰 배경 제품컷. 네이버 쇼핑 대표이미지 가이드에 맞춰 글자는 넣지 않습니다."""
    refs = ws.photos()[: settings["gemini"]["max_reference_photos"]]
    if not refs:
        raise ValueError("실사진(photos/)이 없습니다.")
    prompt = write_prompt(writer, ws, kind="cutout", refs=refs, ratio="1:1",
                          scene="쇼핑 검색 결과에 보이는 대표이미지. 정사각형, 제품이 화면의 약 80%를 차지.")
    path = ws.work_dir / "thumbnail.png"
    path.write_bytes(painter.image(prompt, refs, "1:1"))
    (ws.work_dir / "thumbnail.txt").write_text(prompt, encoding="utf-8")
    return path


def square_on_white(src: Path, size: int) -> Image.Image:
    """정사각형 흰 캔버스 가운데에 맞춰 넣기."""
    with Image.open(src) as im:
        im = im.convert("RGBA")
        im.thumbnail((size, size), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (size, size), "white")
        canvas.paste(im, ((size - im.width) // 2, (size - im.height) // 2), im)
        return canvas


def to_bytes(image: Image.Image, fmt: str, quality: int = 90) -> bytes:
    buf = io.BytesIO()
    if fmt == "jpg":
        image.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True)
    elif fmt == "webp":
        image.save(buf, "WEBP", quality=quality)
    else:
        image.save(buf, "PNG", optimize=True)
    return buf.getvalue()
