"""상세페이지 작업 단계. 화면(ui/detail.py)과 CLI(python -m nstore detail)가 함께 씁니다."""

from __future__ import annotations

from .. import config
from ..master import load_master
from . import images, planner, render
from .compliance import Finding, check_plan
from .gemini import GeminiClient
from .schema import Plan
from .workspace import Workspace

# Gemini에게 넘길 상품 정보 (긴 상세설명 원문은 빼고)
PRODUCT_FIELDS = [
    "자사몰상품코드", "자사몰상품명", "최종상품명", "추천상품명", "브랜드", "제조사", "모델명", "품목",
    "원산지", "옵션", "의료기기여부", "허가신고번호", "광고심의번호", "메인키워드", "최종태그", "추천태그",
]


def settings() -> dict:
    return config.load_yaml("settings.yaml")


def product_info(code: str) -> dict:
    """마스터 시트에서 이 상품 정보. 마스터 시트가 없거나 상품이 없으면 코드만."""
    if config.MASTER_PATH.exists():
        master = load_master(config.MASTER_PATH)
        rows = master[master["자사몰상품코드"] == str(code)]
        if len(rows):
            row = rows.iloc[0]
            return {f: str(row.get(f, "")) for f in PRODUCT_FIELDS if str(row.get(f, "")).strip()}
    return {"자사몰상품코드": str(code)}


def product_choices() -> list[tuple[str, str]]:
    """(코드, 표시 이름). 마스터 시트 상품 + 이미 자료 폴더가 있는 상품."""
    choices: dict[str, str] = {}
    if config.MASTER_PATH.exists():
        master = load_master(config.MASTER_PATH)
        for _, row in master.iterrows():
            code = str(row["자사몰상품코드"]).strip()
            if code:
                choices[code] = f"{code} · {row['최종상품명'] or row['추천상품명'] or row['자사몰상품명']}"
    if config.PRODUCTS_DIR.exists():
        for d in sorted(config.PRODUCTS_DIR.iterdir()):
            if d.is_dir():
                choices.setdefault(d.name, f"{d.name} · (마스터 시트에 없음)")
    return list(choices.items())


def keywords_for(product: dict) -> dict:
    tags = product.get("최종태그") or product.get("추천태그") or ""
    return {"main": product.get("메인키워드", ""), "tags": [t for t in tags.split(",") if t]}


def max_generate() -> int:
    return settings()["gemini"]["max_generated_images"]


def run_facts(code: str, client: GeminiClient) -> str:
    ws = Workspace(code)
    facts = planner.extract_facts(ws, client, product_info(code))
    msg = f"자료 정리: 특징 {len(facts.features)}개, 규격 {len(facts.specs)}개"
    return msg + (f", 확인 못 한 항목 {len(facts.unknowns)}개" if facts.unknowns else "")


def run_plan(code: str, client: GeminiClient) -> str:
    product = product_info(code)
    plan = planner.make_plan(Workspace(code), client, product, keywords_for(product), max_generate())
    return f"구성·카피: 섹션 {len(plan.sections)}개 — {plan.concept}"


def run_images(code: str, client: GeminiClient, progress=None) -> str:
    ws = Workspace(code)
    plan = _require_plan(ws)
    return "; ".join(images.generate_missing(ws, client, plan, settings(), progress))


def run_thumbnail(code: str, client: GeminiClient) -> str:
    return f"대표이미지: {images.make_thumbnail(Workspace(code), client, settings())}"


def run_export(code: str, platforms: list[str] | None = None, formats: list[str] | None = None) -> list[str]:
    ws = Workspace(code)
    s = settings()
    return render.export(
        ws, _require_plan(ws), ws.load_theme(), product_info(code), s,
        platforms or list(s["detail"]["platforms"]), formats or ["jpg"],
    )


def run_check(code: str) -> list[Finding]:
    ws = Workspace(code)
    plan = ws.load_plan()
    if plan is None:
        return []
    rules = config.load_yaml("title_rules.yaml")
    return check_plan(plan, ws.load_facts(), rules, product_info(code), ws.approved_copy())


def _require_plan(ws: Workspace) -> Plan:
    plan = ws.load_plan()
    if plan is None:
        raise ValueError(f"{ws.code}: 구성·카피가 아직 없습니다. 먼저 'plan' 단계를 실행하세요.")
    return plan


def codes_with_material() -> list[str]:
    if not config.PRODUCTS_DIR.exists():
        return []
    return [d.name for d in sorted(config.PRODUCTS_DIR.iterdir()) if d.is_dir() and (Workspace(d.name).photos() or Workspace(d.name).docs())]
