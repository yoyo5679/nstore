"""1단계 작업 순서. CLI(python -m nstore)와 화면(app.py)이 같은 함수를 씁니다.

  1. import    아임웹 엑셀 → data/master.xlsx
  2. keywords  품목별 키워드 조사 → data/keywords.xlsx
  3. titles    추천 상품명·태그·검사 → data/master.xlsx
  4. export    스마트스토어 일괄등록 엑셀 → output/smartstore_upload.xlsx
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from . import config
from .cache import Cache
from .keywords import load_keyword_tables, research_item, save_keyword_tables
from .master import build_master, load_master, save_master
from .naver import SearchAdClient, ShoppingClient
from .smartstore import export
from .titles import generate_titles

Progress = Callable[[float, str], None]


def _settings() -> dict:
    return config.load_yaml("settings.yaml")


def run_import(imweb_path: Path, force: bool = False) -> list[str]:
    if config.MASTER_PATH.exists() and not force:
        raise FileExistsError(
            f"{config.MASTER_PATH} 가 이미 있습니다. 엑셀에서 고친 내용이 지워지니, 새로 만들려면 --force 를 붙이세요."
        )
    master, notes = build_master(Path(imweb_path))
    save_master(master, config.MASTER_PATH)
    notes.append(f"저장: {config.MASTER_PATH}")
    return notes


def run_keywords(items: list[str] | None = None, progress: Progress | None = None) -> list[str]:
    settings = _settings()
    item_specs = config.load_yaml("items.yaml")["items"]
    master = load_master(config.MASTER_PATH) if config.MASTER_PATH.exists() else None

    if not items:
        if master is not None:
            items = sorted({i for i in master["품목"] if i})
        else:
            items = list(item_specs)
    unknown = [i for i in items if i not in item_specs]
    if unknown:
        raise ValueError("config/items.yaml 에 없는 품목: " + ", ".join(unknown))

    cache = Cache(config.CACHE_PATH, settings["cache"]["ttl_days"])
    searchad = SearchAdClient.from_env(cache)
    shopping = ShoppingClient.from_env(cache)

    results, notes = [], []
    for n, item in enumerate(items):
        if progress:
            progress(n / len(items), f"{item} 조사 중 ({n + 1}/{len(items)})")
        own_brands = set(master.loc[master["품목"] == item, "브랜드"]) if master is not None else set()
        research = research_item(item, item_specs[item]["seeds"], searchad, shopping, settings, own_brands)
        results.append(research)
        notes.append(
            f"{item}: 관련 키워드 {int((research.table['구분'] != '제외').sum())}개, "
            f"메인 {', '.join(research.main_keywords) or '없음'}, "
            f"추천카테고리 {' > '.join(research.target_category) or '알 수 없음'}"
        )
    if progress:
        progress(1.0, "완료")

    save_keyword_tables(results, config.KEYWORDS_PATH, load_keyword_tables(config.KEYWORDS_PATH))
    notes.append(f"저장: {config.KEYWORDS_PATH} — 품목 시트의 '구분' 칸을 검토·수정한 뒤 상품명을 만드세요.")
    return notes


def run_titles() -> list[str]:
    master = load_master(config.MASTER_PATH)
    tables = load_keyword_tables(config.KEYWORDS_PATH)
    item_specs = config.load_yaml("items.yaml")["items"]
    rules = config.load_yaml("title_rules.yaml")

    # items.yaml 에 category_id 를 나중에 채운 경우 반영
    for item, spec in item_specs.items():
        if spec.get("category_id"):
            master.loc[(master["품목"] == item) & (master["카테고리ID"] == ""), "카테고리ID"] = str(spec["category_id"])

    master, notes = generate_titles(master, tables, item_specs, _settings(), rules)
    save_master(master, config.MASTER_PATH)
    notes.append(f"저장: {config.MASTER_PATH} — 고칠 상품명은 '최종상품명' 칸에 적으세요.")
    return notes


def run_export(template_path: Path | None = None) -> list[str]:
    master = load_master(config.MASTER_PATH)
    rules = config.load_yaml("title_rules.yaml")
    notes = export(master, config.SMARTSTORE_OUTPUT_PATH, template_path, _settings(), rules)
    notes.append(f"저장: {config.SMARTSTORE_OUTPUT_PATH}")
    return notes
