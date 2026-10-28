"""품목별 키워드 조사.

복지용구는 상품 400개가 품목 20개 안쪽으로 묶이므로, 키워드는 상품마다가 아니라
품목마다 한 번 조사해서 같은 품목 상품들이 함께 씁니다.

흐름:
  1. 씨앗 키워드로 쇼핑 검색 → 상위 상품이 가장 많이 속한 카테고리 = 이 품목의 목표 카테고리
  2. 검색광고 키워드 도구 → 연관키워드 + 월간 검색수
  3. 키워드마다 쇼핑 검색 → 등록 상품 수(경쟁), 목표 카테고리 일치율(관련성)
  4. 구분 지정: 메인 / 세부(메인+속성어) / 연관 / 제외
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .master import squash
from .naver import SearchAdClient, ShopResult, ShoppingClient

ROLE_MAIN = "메인"
ROLE_DETAIL = "세부"
ROLE_RELATED = "연관"
ROLE_EXCLUDED = "제외"

KEYWORD_COLUMNS = [
    "키워드", "구분", "월검색수", "PC", "모바일", "상품수", "경쟁강도",
    "카테고리일치율", "광고경쟁", "대표카테고리", "비고",
]
SUMMARY_SHEET = "요약"


@dataclass
class ItemResearch:
    item: str
    target_category: tuple[str, ...]
    table: pd.DataFrame

    @property
    def main_keywords(self) -> list[str]:
        return self.table.loc[self.table["구분"] == ROLE_MAIN, "키워드"].tolist()


def dominant_category(results: Iterable[ShopResult], depth: int) -> tuple[str, ...]:
    counter = Counter(it.category[:depth] for r in results for it in r.items if it.category)
    return counter.most_common(1)[0][0] if counter else ()


def category_share(result: ShopResult, target: tuple[str, ...], depth: int) -> float:
    if not result.items or not target:
        return 0.0
    return sum(1 for it in result.items if it.category[:depth] == target) / len(result.items)


def competitor_brands(results: Iterable[ShopResult], own_brands: Iterable[str], seeds: Iterable[str]) -> set[str]:
    """상위 상품의 브랜드·제조사 중 우리 브랜드가 아닌 것. 이 이름이 든 키워드는 쓰면 안 됩니다."""
    own = {squash(b) for b in own_brands if b}
    seed_text = " ".join(squash(s) for s in seeds)
    brands = set()
    for r in results:
        for it in r.items:
            for name in (it.brand, it.maker):
                b = squash(name)
                if len(b) >= 2 and b not in own and b not in seed_text:
                    brands.add(b)
    return brands


def assign_roles(rows: list[dict], seeds: Iterable[str], main_count: int) -> None:
    """관련 키워드에 메인/세부/연관을 붙입니다. (제외는 이미 붙어 있음)"""
    relevant = sorted((r for r in rows if r["구분"] != ROLE_EXCLUDED), key=lambda r: r["월검색수"], reverse=True)
    pool = {squash(r["키워드"]) for r in relevant} | {squash(s) for s in seeds}

    def is_compound(kw: str, bases: Iterable[str]) -> bool:
        return any(b != kw and b in kw for b in bases)

    mains = [squash(r["키워드"]) for r in relevant if not is_compound(squash(r["키워드"]), pool)][:main_count]
    bases = set(mains) | {squash(s) for s in seeds}
    for r in relevant:
        kw = squash(r["키워드"])
        if kw in mains:
            r["구분"] = ROLE_MAIN
        elif is_compound(kw, bases):
            r["구분"] = ROLE_DETAIL
        else:
            r["구분"] = ROLE_RELATED


def research_item(
    item: str,
    seeds: list[str],
    searchad: SearchAdClient,
    shopping: ShoppingClient,
    settings: dict,
    own_brands: Iterable[str] = (),
) -> ItemResearch:
    cfg = settings["keyword_research"]
    depth, sample = cfg["category_depth"], cfg["sample_size"]

    seed_results = [shopping.search(s, display=sample) for s in seeds]
    target = dominant_category(seed_results, depth)
    rivals = competitor_brands(seed_results, own_brands, seeds)

    seed_set = {squash(s) for s in seeds}
    stats = [
        s for s in searchad.related_keywords(seeds)
        if s.volume >= cfg["min_volume"] or squash(s.keyword) in seed_set
    ]
    stats.sort(key=lambda s: s.volume, reverse=True)

    rows = []
    for stat in stats[: cfg["max_candidates"]]:
        result = shopping.search(stat.keyword, display=sample)
        share = category_share(result, target, depth)
        row = {
            "키워드": stat.keyword,
            "구분": "",
            "월검색수": stat.volume,
            "PC": stat.pc,
            "모바일": stat.mobile,
            "상품수": result.total,
            "경쟁강도": round(result.total / max(stat.volume, 1), 2),
            "카테고리일치율": round(share, 2),
            "광고경쟁": stat.ad_competition,
            "대표카테고리": " > ".join(dominant_category([result], depth)),
            "비고": "",
        }
        kw = squash(stat.keyword)
        rival = next((b for b in sorted(rivals, key=len, reverse=True) if b in kw), None)
        if rival:
            row["구분"], row["비고"] = ROLE_EXCLUDED, f"타사 브랜드 포함({rival})"
        elif share < cfg["min_category_match"]:
            row["구분"], row["비고"] = ROLE_EXCLUDED, "카테고리 불일치"
        rows.append(row)

    assign_roles(rows, seeds, cfg["main_candidates"])
    table = pd.DataFrame(rows, columns=KEYWORD_COLUMNS)
    return ItemResearch(item=item, target_category=target, table=table)


# ---------------------------------------------------------------- 엑셀 저장/읽기

_BAD_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")


def _sheet_name(item: str) -> str:
    return _BAD_SHEET_CHARS.sub("_", item)[:31]


def save_keyword_tables(results: list[ItemResearch], path: Path, existing: dict[str, pd.DataFrame] | None = None) -> None:
    """품목별 시트 + 요약 시트. existing 에 있던 다른 품목 시트는 그대로 둡니다."""
    tables = dict(existing or {})
    old_summary = tables.pop(SUMMARY_SHEET, None)
    targets = {}
    for r in results:
        tables[r.item] = r.table
        targets[r.item] = " > ".join(r.target_category)

    summary = []
    for item, table in tables.items():
        summary.append({
            "품목": item,
            "추천카테고리": targets.get(item, ""),
            "메인키워드": ", ".join(table.loc[table["구분"] == ROLE_MAIN, "키워드"]),
            "관련키워드수": int((table["구분"] != ROLE_EXCLUDED).sum()),
            "제외키워드수": int((table["구분"] == ROLE_EXCLUDED).sum()),
        })
    if old_summary is not None:
        old = old_summary.set_index("품목")["추천카테고리"].to_dict()
        for row in summary:
            row["추천카테고리"] = row["추천카테고리"] or old.get(row["품목"], "")

    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(summary).to_excel(writer, sheet_name=SUMMARY_SHEET, index=False)
        writer.sheets[SUMMARY_SHEET].column_dimensions["B"].width = 45
        writer.sheets[SUMMARY_SHEET].column_dimensions["C"].width = 45
        for item, table in tables.items():
            name = _sheet_name(item)
            table.to_excel(writer, sheet_name=name, index=False)
            writer.sheets[name].column_dimensions["A"].width = 24
            writer.sheets[name].column_dimensions["J"].width = 40
            writer.sheets[name].freeze_panes = "B2"


def load_keyword_tables(path: Path) -> dict[str, pd.DataFrame]:
    """{품목: 키워드 표}. 사람이 엑셀에서 고친 '구분' 값을 그대로 씁니다. 요약 시트도 포함."""
    if not path.exists():
        return {}
    sheets = pd.read_excel(path, sheet_name=None, dtype=str)
    tables = {}
    for name, df in sheets.items():
        df = df.fillna("")
        if name != SUMMARY_SHEET:
            for col in ("월검색수", "PC", "모바일", "상품수"):
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
            for col in ("경쟁강도", "카테고리일치율"):
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        tables[name] = df
    return tables
