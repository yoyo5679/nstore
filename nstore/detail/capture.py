"""링크(제품 설명 페이지, 레퍼런스 상세페이지)를 브라우저로 열어 캡처합니다.

한국 상세페이지는 대부분 긴 이미지라 글자만 긁으면 내용을 놓칩니다.
그래서 끝까지 스크롤해 늦게 뜨는 이미지까지 불러온 뒤, 화면을 조각으로 찍고 보이는 글자도 함께 저장합니다.
저장한 파일은 사진·카탈로그와 똑같이 Claude가 읽습니다.
"""

from __future__ import annotations

import os
from pathlib import Path

# 휴대폰 화면으로 엽니다: 상세페이지 이미지가 화면 폭에 맞게 세로로 이어져 읽기 좋습니다.
VIEWPORT = {"width": 430, "height": 932}
SCALE = 2  # 캡처 해상도 (430 × 2 = 860px)
SLICE_HEIGHT = 650  # 조각 하나의 높이 (화면 기준 px) — 너무 길면 Claude가 줄여 읽어 글자가 뭉개짐
MAX_SLICES = 30
MAX_TEXT = 40_000
USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
)

SCROLL_TO_BOTTOM = """async () => {
  let last = -1;
  for (let i = 0; i < 80; i++) {
    window.scrollBy(0, window.innerHeight);
    await new Promise(r => setTimeout(r, 250));
    const h = document.documentElement.scrollHeight;
    if (window.scrollY + window.innerHeight >= h && h === last) break;
    last = h;
  }
  window.scrollTo(0, 0);
  return document.documentElement.scrollHeight;
}"""


class CaptureError(RuntimeError):
    pass


def read_links(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    return [line for line in lines if line.startswith(("http://", "https://"))]


def capture(urls: list[str], out_dir: Path, prefix: str, max_slices: int = MAX_SLICES) -> tuple[list[Path], list[str]]:
    """링크마다 <prefix>-NN.txt 와 <prefix>-NN-MM.png 조각들을 저장. (저장한 파일, 안내 메시지)"""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    saved, notes = [], []
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(executable_path=os.environ.get("NSTORE_CHROMIUM") or None)
        except PlaywrightError as e:
            raise CaptureError("브라우저를 열지 못했습니다. 터미널에서 'playwright install chromium' 을 실행하세요.") from e
        try:
            for n, url in enumerate(urls, start=1):
                tag = f"{prefix}-{n:02d}"
                for old in out_dir.glob(f"{tag}*"):
                    old.unlink()
                page = browser.new_page(viewport=VIEWPORT, device_scale_factor=SCALE, user_agent=USER_AGENT,
                                        is_mobile=True, has_touch=True)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                    height = page.evaluate(SCROLL_TO_BOTTOM)
                    try:
                        page.wait_for_load_state("networkidle", timeout=10_000)
                    except PlaywrightError:
                        pass  # 광고·추적 요청이 계속 오가는 사이트는 그냥 진행
                    height = max(height, page.evaluate("document.documentElement.scrollHeight"))

                    text = page.inner_text("body")[:MAX_TEXT]
                    txt = out_dir / f"{tag}.txt"
                    txt.write_text(f"출처: {url}\n\n{text}", encoding="utf-8")
                    saved.append(txt)

                    slices = 0
                    for top in range(0, height, SLICE_HEIGHT):
                        if slices >= max_slices:
                            notes.append(f"{url}: 페이지가 길어 앞부분 {max_slices}조각만 캡처했습니다.")
                            break
                        clip = {"x": 0, "y": top, "width": VIEWPORT["width"], "height": min(SLICE_HEIGHT, height - top)}
                        shot = out_dir / f"{tag}-{slices + 1:02d}.png"
                        page.screenshot(path=str(shot), clip=clip, full_page=True)
                        saved.append(shot)
                        slices += 1
                    notes.append(f"{url}: 캡처 {slices}장, 글자 {len(text):,}자")
                except PlaywrightError as e:
                    notes.append(f"{url}: 열지 못했습니다 — 로그인이 필요하거나 자동 접속을 막는 사이트일 수 있습니다. ({str(e)[:100]})")
                finally:
                    page.close()
        finally:
            browser.close()
    return saved, notes
