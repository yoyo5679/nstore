"""마스터 시트: 모든 단계가 함께 쓰는 상품 목록 (data/master.xlsx).

아임웹 엑셀을 읽어 만들고, 사람이 엑셀에서 품목·브랜드·모델명 등을 채우거나 고친 뒤
다음 단계로 넘깁니다.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import pandas as pd

from .config import load_yaml
from .excel_io import match_columns, read_table

# 아임웹에서 가져오는 칸
SOURCE_COLUMNS = [
    "자사몰상품코드",
    "자사몰상품명",
    "판매가",
    "재고",
    "브랜드",
    "제조사",
    "모델명",
    "원산지",
    "대표이미지",
    "추가이미지",
    "요약설명",
    "상세설명원본",
    "옵션",
]
# 사람이 채우거나 확인하는 칸
MANUAL_COLUMNS = [
    "품목",
    "품목분류메모",
    "카테고리ID",
    "의료기기여부",
    "허가신고번호",
    "광고심의번호",
]
# 상품명 생성 단계가 채우는 칸 (최종* 칸은 사람이 고친 값; 비어 있으면 추천값을 씀)
GENERATED_COLUMNS = [
    "메인키워드",
    "추천상품명",
    "최종상품명",
    "추천태그",
    "최종태그",
    "확인필요속성",
    "검사결과",
]
MASTER_COLUMNS = SOURCE_COLUMNS + MANUAL_COLUMNS + GENERATED_COLUMNS

_TAG_RE = re.compile(r"<[^>]+>")


def html_to_text(value: str) -> str:
    text = _TAG_RE.sub(" ", value or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def squash(text: str) -> str:
    """띄어쓰기를 없애고 소문자로. 키워드 포함 여부 비교용."""
    return re.sub(r"\s+", "", text or "").lower()


def classify_item(name: str, items: dict) -> tuple[str, str]:
    """상품명으로 품목 추정. (품목, 메모). 가장 긴 별칭이 맞는 품목을 고르고, 동률이면 비워둡니다."""
    target = squash(name)
    best_len, matches = 0, []
    for item, spec in items.items():
        hits = [len(squash(a)) for a in spec.get("aliases", []) if squash(a) in target]
        if not hits:
            continue
        longest = max(hits)
        if longest > best_len:
            best_len, matches = longest, [item]
        elif longest == best_len:
            matches.append(item)
    if len(matches) == 1:
        return matches[0], ""
    if matches:
        return "", "품목 후보: " + " / ".join(matches)
    return "", "품목 자동분류 실패"


def build_master(imweb_path: Path) -> tuple[pd.DataFrame, list[str]]:
    """아임웹 엑셀 → 마스터 시트. (표, 안내 메시지 목록)"""
    candidates = load_yaml("imweb_columns.yaml")
    items = load_yaml("items.yaml")["items"]

    expected = [name for names in candidates.values() for name in names]
    raw = read_table(imweb_path, expected)
    mapping = match_columns(raw.columns, candidates)

    notes = [f"아임웹 상품 {len(raw)}개를 읽었습니다."]
    missing = [c for c in SOURCE_COLUMNS if c not in mapping]
    if missing:
        notes.append("아임웹 엑셀에서 못 찾은 칸: " + ", ".join(missing)
                     + " (config/imweb_columns.yaml 에 헤더 이름을 추가하면 됩니다)")
    if "자사몰상품명" not in mapping:
        raise ValueError("아임웹 엑셀에서 상품명 칸을 찾지 못했습니다. config/imweb_columns.yaml 을 확인하세요.")

    master = pd.DataFrame({col: raw[mapping[col]] if col in mapping else "" for col in SOURCE_COLUMNS})
    for col in MANUAL_COLUMNS + GENERATED_COLUMNS:
        master[col] = ""
    master["상세설명원본"] = master["상세설명원본"].map(html_to_text)

    classified = master["자사몰상품명"].map(lambda n: classify_item(n, items))
    master["품목"] = classified.map(lambda r: r[0])
    master["품목분류메모"] = classified.map(lambda r: r[1])
    master["카테고리ID"] = master["품목"].map(lambda i: str(items.get(i, {}).get("category_id", "") or ""))

    unclassified = (master["품목"] == "").sum()
    if unclassified:
        notes.append(f"품목을 정하지 못한 상품 {unclassified}개 — 마스터 시트의 '품목' 칸을 직접 채워주세요.")
    return master[MASTER_COLUMNS], notes


def load_master(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, dtype=str).fillna("")
    for col in MASTER_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df


def save_master(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="상품", index=False)
        sheet = writer.sheets["상품"]
        sheet.freeze_panes = "C2"
        for i, col in enumerate(df.columns, start=1):
            width = 40 if col in ("자사몰상품명", "추천상품명", "최종상품명", "추천태그", "검사결과") else 14
            sheet.column_dimensions[sheet.cell(row=1, column=i).column_letter].width = width
