"""상품별 작업 폴더.

products/<상품코드>/
  photos/             여러 각도 실사진 (jpg, png, webp)
  docs/               카탈로그·사용설명서 (pdf 또는 이미지), 링크 캡처(link-NN*)
  links.txt           (선택) 제품 설명 링크, 한 줄에 하나 — 캡처해서 docs/ 에 넣음
  reviews.txt         (선택) 고객 리뷰를 붙여넣은 텍스트 — 소구점 분석용
  approved_copy.txt   (의료기기) 광고 자율심의를 받은 문구
  theme.json          (선택) 이 상품만 다른 디자인을 쓸 때
  reference.json      (선택) 이 상품만 다른 레퍼런스(섹션 흐름·말투·사진 분위기)를 쓸 때
  work/
    facts.json        자료에서 뽑은 사실
    reviews.json      리뷰 분석 결과
    plan.json         섹션 구성·카피·이미지 계획 (현재 버전)
    images/<섹션ID>.png   AI가 만든 이미지
    history/          되돌리기용 이전 버전

폴더 이름을 영어로 둔 이유: 맥 Finder에서 만든 한글 폴더 이름은 내부 표기 방식이 달라 프로그램이 못 찾는 일이 있습니다.
"""

from __future__ import annotations

import json
import re
import shutil
import unicodedata
from pathlib import Path

from .. import config
from .schema import Facts, Plan, ReferenceGuide, ReviewInsights, Theme

PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
DOC_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".txt", ".md"}
_UNSAFE = re.compile(r"[^\w.-]+")


def safe_code(code: str) -> str:
    text = unicodedata.normalize("NFC", str(code).strip())
    return _UNSAFE.sub("_", text) or "product"


class Workspace:
    def __init__(self, code: str, root: Path | None = None):
        self.code = safe_code(code)
        self.dir = (root or config.PRODUCTS_DIR) / self.code
        self.photos_dir = self.dir / "photos"
        self.docs_dir = self.dir / "docs"
        self.work_dir = self.dir / "work"
        self.images_dir = self.work_dir / "images"
        self.history_dir = self.work_dir / "history"

    def ensure(self) -> "Workspace":
        for d in (self.photos_dir, self.docs_dir, self.images_dir, self.history_dir):
            d.mkdir(parents=True, exist_ok=True)
        return self

    # ------------------------------------------------------------ 입력 자료

    @staticmethod
    def _files(folder: Path, exts: set[str]) -> list[Path]:
        if not folder.exists():
            return []
        return sorted(p for p in folder.iterdir() if p.suffix.lower() in exts and not p.name.startswith("."))

    def photos(self) -> list[Path]:
        return self._files(self.photos_dir, PHOTO_EXTS)

    def docs(self) -> list[Path]:
        return self._files(self.docs_dir, DOC_EXTS)

    def photo(self, name: str) -> Path | None:
        path = self.photos_dir / name
        return path if name and path.exists() else None

    def _text(self, name: str) -> str:
        path = self.dir / name
        return path.read_text(encoding="utf-8").strip() if path.exists() else ""

    def reviews_text(self) -> str:
        return self._text("reviews.txt")

    def approved_copy(self) -> str:
        return self._text("approved_copy.txt")

    def save_text(self, name: str, text: str) -> None:
        self.ensure()
        (self.dir / name).write_text(text, encoding="utf-8")

    def add_file(self, folder: Path, name: str, data: bytes) -> Path:
        self.ensure()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / safe_code(Path(name).stem)
        path = path.with_suffix(Path(name).suffix.lower())
        path.write_bytes(data)
        return path

    # ------------------------------------------------------------ 결과물

    def _load(self, name: str, model):
        path = self.work_dir / name
        return model.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None

    def _save(self, name: str, obj) -> None:
        self.ensure()
        (self.work_dir / name).write_text(obj.model_dump_json(indent=2), encoding="utf-8")

    def load_facts(self) -> Facts | None:
        return self._load("facts.json", Facts)

    def save_facts(self, facts: Facts) -> None:
        self._save("facts.json", facts)

    def load_reviews(self) -> ReviewInsights | None:
        return self._load("reviews.json", ReviewInsights)

    def save_reviews(self, insights: ReviewInsights) -> None:
        self._save("reviews.json", insights)

    def load_plan(self) -> Plan | None:
        return self._load("plan.json", Plan)

    def load_theme(self) -> Theme | None:
        own = self.dir / "theme.json"
        for path in (own, config.THEME_PATH):
            if path.exists():
                return Theme.model_validate_json(path.read_text(encoding="utf-8"))
        return None

    def load_reference(self) -> ReferenceGuide | None:
        """이 상품의 레퍼런스, 없으면 모든 상품 공통 레퍼런스."""
        for path in (self.dir / "reference.json", config.REFERENCE_PATH):
            if path.exists():
                return ReferenceGuide.model_validate_json(path.read_text(encoding="utf-8"))
        return None

    def links_path(self) -> Path:
        return self.dir / "links.txt"

    def captured_links(self) -> list[Path]:
        return sorted(self.docs_dir.glob("link-*")) if self.docs_dir.exists() else []

    # ------------------------------------------------------------ 버전 관리 (되돌리기)

    def _versions(self) -> list[Path]:
        return sorted(self.history_dir.glob("plan-*.json")) if self.history_dir.exists() else []

    def save_plan(self, plan: Plan, note: str = "") -> None:
        """현재 버전으로 저장하고 기록을 남깁니다."""
        self._save("plan.json", plan)
        n = len(self._versions()) + 1
        record = {"note": note, "plan": json.loads(plan.model_dump_json())}
        (self.history_dir / f"plan-{n:04d}.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    def history(self) -> list[str]:
        return [json.loads(p.read_text(encoding="utf-8")).get("note", "") for p in self._versions()]

    def undo(self) -> Plan | None:
        """마지막 변경을 취소하고 바로 전 버전으로 돌아갑니다. 돌아갈 버전이 없으면 None."""
        versions = self._versions()
        if len(versions) < 2:
            return None
        versions[-1].unlink()
        plan = Plan.model_validate(json.loads(versions[-2].read_text(encoding="utf-8"))["plan"])
        self._save("plan.json", plan)
        return plan

    # ------------------------------------------------------------ 섹션 이미지

    def section_image(self, section_id: str) -> Path | None:
        path = self.images_dir / f"{section_id}.png"
        return path if path.exists() else None

    def save_section_image(self, section_id: str, data: bytes) -> Path:
        """새 이미지를 저장하고 이전 이미지는 기록 폴더에 남깁니다."""
        self.ensure()
        path = self.images_dir / f"{section_id}.png"
        if path.exists():
            n = len(list(self.history_dir.glob(f"img-{section_id}-*.png"))) + 1
            shutil.copy2(path, self.history_dir / f"img-{section_id}-{n:03d}.png")
        path.write_bytes(data)
        return path

    def save_image_prompt(self, section_id: str, prompt: str) -> None:
        """이미지를 만들 때 Gemini에 실제로 보낸 프롬프트 (화면에서 확인용)."""
        (self.images_dir / f"{section_id}.txt").write_text(prompt, encoding="utf-8")

    def image_prompt(self, section_id: str) -> str:
        path = self.images_dir / f"{section_id}.txt"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def has_image_history(self, section_id: str) -> bool:
        return any(self.history_dir.glob(f"img-{section_id}-*.png")) if self.history_dir.exists() else False

    def undo_section_image(self, section_id: str) -> bool:
        olds = sorted(self.history_dir.glob(f"img-{section_id}-*.png"))
        if not olds:
            return False
        shutil.move(olds[-1], self.images_dir / f"{section_id}.png")
        return True
