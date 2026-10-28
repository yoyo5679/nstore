"""기획(plan) + 테마 → HTML → 플랫폼 규격 이미지.

디자인은 폭 860px 기준 한 벌만 만들고, 브라우저 배율(device scale factor)로
쿠팡 780px·토스 1,080px 등 다른 폭으로 찍어냅니다. 글자가 흐려지지 않고 배치도 같습니다.
"""

from __future__ import annotations

import base64
import io
import os
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape
from PIL import Image

from .. import config
from .images import aspect_ratio, square_on_white, to_bytes
from .schema import Plan, Theme
from .theme import DEFAULT_THEME, on_color
from .workspace import Workspace

TEMPLATES = Path(__file__).parent / "templates"
WEBP_MAX = 16383  # WEBP 한 장의 최대 높이


def _br(text: str) -> Markup:
    return Markup("<br>").join(escape(str(text).replace("\\n", "\n")).split("\n"))


_env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["j2", "html"]))
_env.filters["br"] = _br


def _data_uri(path: Path, max_width: int) -> str:
    return _encoded(str(path), path.stat().st_mtime, max_width)


@lru_cache(maxsize=64)
def _encoded(path: str, mtime: float, max_width: int) -> str:
    with Image.open(path) as im:
        im = im.convert("RGB")
        if im.width > max_width:
            im = im.resize((max_width, round(im.height * max_width / im.width)), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def notice_lines(product: dict) -> list[str]:
    """페이지 맨 아래 법정 표기 (값이 있는 것만)."""
    lines = []
    for label, key in (("제조사", "제조사"), ("의료기기 허가·신고번호", "허가신고번호"), ("의료기기 광고심의필", "광고심의번호")):
        value = str(product.get(key, "")).strip()
        if value:
            lines.append(f"{label}: {value}")
    if str(product.get("광고심의번호", "")).strip():
        lines.append("이 제품은 의료기기이며, 사용 전 사용상의 주의사항과 사용방법을 잘 읽고 사용하십시오.")
    return lines


def render_html(plan: Plan, theme: Theme | None, ws: Workspace, product: dict, settings: dict, image_width: int) -> str:
    theme = theme or DEFAULT_THEME
    sections, feature_no, alt = [], 0, False
    for s in plan.sections:
        data = s.model_dump()
        data["entries"] = data.pop("items")  # 템플릿에서 dict.items 와 헷갈리지 않게
        if s.type == "feature":
            feature_no += 1
            data["eyebrow"] = s.eyebrow or f"POINT {feature_no:02d}"
        if s.type in ("hero", "cta"):
            data["alt"] = False
        else:
            alt = not alt
            data["alt"] = alt

        data["image_src"], data["placeholder"] = "", None
        if s.image.mode == "photo" and ws.photo(s.image.photo):
            data["image_src"] = _data_uri(ws.photo(s.image.photo), image_width)
        elif s.image.mode == "generate":
            generated = ws.section_image(s.id)
            if generated:
                data["image_src"] = _data_uri(generated, image_width)
            else:
                data["placeholder"] = {"ratio": aspect_ratio(s, settings).replace(":", " / "), "prompt": s.image.prompt[:120]}
        sections.append(data)

    return _env.get_template("page.html.j2").render(
        sections=sections,
        theme=theme,
        on_primary=on_color(theme.primary),
        width=settings["detail"]["base_width"],
        notice=notice_lines(product),
    )


def _launch(playwright):
    # 기본은 'playwright install chromium' 으로 받은 브라우저. 다른 크롬을 쓰려면 NSTORE_CHROMIUM 에 경로 지정.
    try:
        return playwright.chromium.launch(executable_path=os.environ.get("NSTORE_CHROMIUM") or None)
    except Exception as e:  # playwright 는 브라우저가 없을 때 자체 Error 를 던짐
        raise ValueError(f"이미지로 찍을 브라우저를 열지 못했습니다. 터미널에서 'playwright install chromium' 을 실행하세요. ({str(e)[:120]})") from e


def export(
    ws: Workspace,
    plan: Plan,
    theme: Theme | None,
    product: dict,
    settings: dict,
    platforms: list[str],
    formats: list[str],
) -> list[str]:
    """플랫폼별 폭으로 섹션 이미지·전체 이미지·대표이미지를 저장합니다."""
    from playwright.sync_api import sync_playwright

    detail = settings["detail"]
    base = detail["base_width"]
    quality = detail.get("jpg_quality", 90)
    notes = []
    with sync_playwright() as p:
        browser = _launch(p)
        try:
            for key in platforms:
                platform = detail["platforms"][key]
                width = platform["width"]
                out = config.DETAIL_OUTPUT_DIR / ws.code / key
                (out / "sections").mkdir(parents=True, exist_ok=True)

                page = browser.new_page(viewport={"width": base, "height": 1200}, device_scale_factor=width / base)
                page.set_content(render_html(plan, theme, ws, product, settings, width), wait_until="networkidle")
                page.evaluate("document.fonts.ready.then(() => true)")

                shots = []
                for n, el in enumerate(page.query_selector_all("section"), start=1):
                    sid = el.get_attribute("id") or f"{n:02d}"
                    with Image.open(io.BytesIO(el.screenshot(type="png"))) as im:
                        shot = im.convert("RGB")
                    shots.append(shot)
                    for fmt in formats:
                        (out / "sections" / f"{n:02d}_{sid}.{fmt}").write_bytes(to_bytes(shot, fmt, quality))
                page.close()

                full = Image.new("RGB", (max(s.width for s in shots), sum(s.height for s in shots)), "white")
                y = 0
                for shot in shots:
                    full.paste(shot, (0, y))
                    y += shot.height
                for fmt in formats:
                    if fmt == "webp" and full.height > WEBP_MAX:
                        notes.append(f"{platform['label']}: 전체 이미지가 너무 길어 WEBP 한 장으로는 저장하지 않았습니다 (섹션별 WEBP는 저장됨).")
                        continue
                    (out / f"full.{fmt}").write_bytes(to_bytes(full, fmt, quality))

                thumb_src = ws.work_dir / "thumbnail.png"
                if thumb_src.exists():
                    thumb = square_on_white(thumb_src, platform["thumbnail"])
                    for fmt in formats:
                        (out / f"thumbnail.{fmt}").write_bytes(to_bytes(thumb, fmt, quality))
                notes.append(f"{platform['label']} {width}px: 섹션 {len(shots)}장 + 전체 1장 ({full.width}×{full.height}) → {out}")
        finally:
            browser.close()
    pending = [sec.id for sec in plan.sections if sec.image.mode == "generate" and not ws.section_image(sec.id)]
    if pending:
        notes.append(f"AI 이미지가 아직 없는 섹션({', '.join(pending)})은 빈 자리 표시가 그대로 찍혔습니다. ③ 이미지에서 만든 뒤 다시 내보내세요.")
    if not (ws.work_dir / "thumbnail.png").exists():
        notes.append("대표이미지는 아직 없습니다. '대표이미지 만들기'를 누르면 흰 배경 제품컷을 만듭니다.")
    return notes
