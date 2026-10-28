"""연출 컷 생성·배경 편집 (Gemini 이미지 모델 = Nano Banana).

실사진을 참조 이미지로 함께 넣어 제품 모양이 바뀌지 않게 하고, 이미지 안에 글자는 넣지 않습니다.
(글자·스펙은 HTML로 얹어서 오타·지어낸 숫자가 생기지 않게 합니다.)
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from .gemini import GeminiClient
from .schema import Plan, Section
from .workspace import Workspace

KEEP_PRODUCT = (
    "The product must look exactly like the product in the reference photos: same shape, proportions, "
    "colors, materials, parts and logo. Do not redesign, simplify or add parts. "
    "Do not add any text, letters, numbers, captions, logos or watermarks to the image. Photorealistic."
)

KIND_PROMPTS = {
    "scene": "Create a lifestyle photo of this product being used. Scene: {prompt}. "
             "Bright, clean, warm Korean home interior, natural window light, Korean people if any people appear.",
    "detail": "Create a close-up detail photo of this product. Focus: {prompt}. "
              "Soft studio lighting, shallow depth of field, clean neutral background.",
    "cutout": "Show this product alone on a pure white (#FFFFFF) background, centered, full product visible, "
              "soft natural shadow under it, e-commerce catalog style. {prompt}",
    "extend": "Extend the background of this photo outward so it fills the new frame naturally. "
              "Keep the original photo content unchanged. {prompt}",
}


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


def generate_section_image(ws: Workspace, client: GeminiClient, section: Section, settings: dict, instruction: str = "") -> Path:
    kind = section.image.kind if section.image.kind in KIND_PROMPTS else "scene"
    if kind == "extend" and not ws.photo(section.image.photo):
        kind = "scene"
    prompt = KIND_PROMPTS[kind].format(prompt=section.image.prompt or "")
    if instruction:
        prompt += f" Additional request: {instruction}."
    refs = _references(ws, section, settings["gemini"]["max_reference_photos"])
    if not refs:
        raise ValueError("실사진(photos/)이 없어 제품 모양을 맞출 수 없습니다. 사진을 먼저 올리세요.")
    data = client.image(f"{prompt} {KEEP_PRODUCT}", refs, aspect_ratio(section, settings))
    return ws.save_section_image(section.id, data)


def edit_section_image(ws: Workspace, client: GeminiClient, section: Section, instruction: str, settings: dict) -> Path:
    """지금 이미지를 바탕으로 말한 부분만 고칩니다."""
    current = ws.section_image(section.id) or ws.photo(section.image.photo)
    if current is None:
        return generate_section_image(ws, client, section, settings, instruction)
    refs = [current] + [p for p in ws.photos() if p != current][: settings["gemini"]["max_reference_photos"] - 1]
    prompt = (f"Edit the first image: {instruction}. Change only what is requested and keep everything else the same. "
              f"{KEEP_PRODUCT}")
    data = client.image(prompt, refs, aspect_ratio(section, settings))
    return ws.save_section_image(section.id, data)


def generate_missing(ws: Workspace, client: GeminiClient, plan: Plan, settings: dict, progress=None) -> list[str]:
    """아직 이미지가 없는 'generate' 섹션만 만듭니다."""
    targets = [s for s in plan.sections if s.image.mode == "generate" and not ws.section_image(s.id)]
    notes = []
    for n, section in enumerate(targets):
        if progress:
            progress(n / len(targets), f"이미지 생성 중 {n + 1}/{len(targets)} ({section.id})")
        generate_section_image(ws, client, section, settings)
        notes.append(f"{section.id} 이미지 생성")
    return notes or ["새로 만들 이미지가 없습니다."]


def make_thumbnail(ws: Workspace, client: GeminiClient, settings: dict) -> Path:
    """대표이미지용 흰 배경 제품컷. 네이버 쇼핑 대표이미지 가이드에 맞춰 글자는 넣지 않습니다."""
    photos = ws.photos()
    if not photos:
        raise ValueError("실사진(photos/)이 없습니다.")
    prompt = KIND_PROMPTS["cutout"].format(prompt="Square composition, product fills about 80% of the frame.")
    data = client.image(f"{prompt} {KEEP_PRODUCT}", photos[: settings["gemini"]["max_reference_photos"]], "1:1")
    path = ws.work_dir / "thumbnail.png"
    path.write_bytes(data)
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
