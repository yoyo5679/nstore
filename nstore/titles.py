"""상품명·태그 만들기와 검사.

상품명 = 브랜드 + 모델명 + 속성어(접이식, 경량 …) + 메인키워드

- 메인키워드는 품목 키워드 표에서 '메인' 중 검색수가 가장 많은 것 하나만 씁니다.
  같은 뜻의 다른 이름(노인보행기/실버카 등)을 상품명에 나열하면 동의어 반복으로 감점되므로 태그로 보냅니다.
- 속성어는 '세부' 키워드(예: 접이식성인용보행기)에서 메인을 뺀 나머지(접이식)입니다.
  이 말이 자사몰 상품명·설명에 실제로 있을 때만 넣습니다. 없는 속성을 붙이면 허위 표시가 됩니다.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import pandas as pd

from .keywords import ROLE_DETAIL, ROLE_EXCLUDED, ROLE_MAIN
from .master import squash

_WORD_RE = re.compile(r"[\w-]+")

LEVEL_ERROR = "오류"
LEVEL_WARNING = "주의"


@dataclass
class Issue:
    level: str
    message: str

    def __str__(self) -> str:
        return f"{self.level}: {self.message}"


@dataclass
class TitleResult:
    main_keyword: str
    title: str
    tags: list[str]
    unconfirmed: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


def check_title(title: str, rules: dict, settings: dict) -> list[Issue]:
    cfg = settings["title"]
    issues = []
    length = len(title)
    if length > cfg["max_length"]:
        issues.append(Issue(LEVEL_ERROR, f"{length}자 — 스마트스토어 최대 {cfg['max_length']}자 초과"))
    elif length > cfg["recommended_length"]:
        issues.append(Issue(LEVEL_WARNING, f"{length}자 — 권장 {cfg['recommended_length']}자 초과"))

    compact = squash(title)  # '무료 배송'처럼 띄어 써도 잡히도록
    for phrase in rules.get("error_phrases", []):
        if squash(str(phrase)) in compact:
            issues.append(Issue(LEVEL_ERROR, f"금지 문구 '{phrase}'"))
    for phrase in rules.get("warning_phrases", []):
        if squash(str(phrase)) in compact:
            issues.append(Issue(LEVEL_WARNING, f"확인 필요 표현 '{phrase}'"))

    allowed = set(rules.get("allowed_symbols", ""))
    symbols = sorted({ch for ch in title if not (ch.isalnum() or ch.isspace() or ch in allowed)})
    if symbols:
        issues.append(Issue(LEVEL_WARNING, "특수문자 " + " ".join(symbols)))

    repeated = [w for w, n in Counter(_WORD_RE.findall(title)).items() if n > 1]
    if repeated:
        issues.append(Issue(LEVEL_WARNING, "같은 단어 반복: " + ", ".join(repeated)))
    return issues


def _has_any(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)


def compose(product: dict, table: pd.DataFrame, item: str, seeds: list[str], settings: dict, rules: dict) -> TitleResult:
    cfg = settings["title"]
    table = table[table["구분"] != ROLE_EXCLUDED].sort_values("월검색수", ascending=False, kind="stable")
    mains = table.loc[table["구분"] == ROLE_MAIN, "키워드"].tolist()
    main = mains[0] if mains else item

    product_text = squash(" ".join(
        str(product.get(c, "")) for c in ("자사몰상품명", "모델명", "요약설명", "상세설명원본", "옵션")
    ))
    always_true = [squash(w) for w in cfg["always_true_modifiers"]]
    intent = [squash(w) for w in cfg["intent_words"]]
    banned = [squash(str(p)) for p in rules.get("error_phrases", []) + rules.get("warning_phrases", [])]
    bases = sorted({squash(k) for k in mains} | {squash(s) for s in seeds}, key=len, reverse=True)

    # 세부 키워드 → 속성어, 상품 정보로 확인되는지
    detail_ok: dict[str, bool] = {}
    confirmed, unconfirmed = [], []
    for kw in table.loc[table["구분"] == ROLE_DETAIL, "키워드"]:
        k = squash(kw)
        base = next((b for b in bases if b != k and b in k), None)
        modifier = k.replace(base, "", 1) if base else ""
        if not modifier or _has_any(k, intent):
            detail_ok[kw] = False
            continue
        ok = modifier in product_text or modifier in always_true
        detail_ok[kw] = ok
        (confirmed if ok else unconfirmed).append(modifier)

    chosen: list[str] = []
    for mod in confirmed:
        if len(chosen) >= cfg["max_modifiers"]:
            break
        if mod in squash(main) or any(mod in c or c in mod for c in chosen):
            continue
        chosen.append(mod)

    def build(mods: list[str]) -> str:
        parts: list[str] = []
        for part in [product.get("브랜드", ""), product.get("모델명", ""), *mods, main]:
            part = str(part).strip()
            if part and squash(part) not in squash(" ".join(parts)):
                parts.append(part)
        return " ".join(parts)

    title = build(chosen)
    while len(title) > cfg["recommended_length"] and chosen:
        chosen.pop()
        title = build(chosen)

    used = squash(title)
    tags = []
    for _, row in table.iterrows():
        kw, k = row["키워드"], squash(row["키워드"])
        if len(tags) >= cfg["max_tags"]:
            break
        if k in used or _has_any(k, intent) or _has_any(k, banned):
            continue
        if row["구분"] == ROLE_DETAIL and not detail_ok.get(kw, False):
            continue
        tags.append(kw)

    issues = []
    if not mains:
        issues.append(Issue(LEVEL_WARNING, "키워드 조사 결과에 메인 키워드가 없어 품목명을 그대로 씀"))
    if not str(product.get("브랜드", "")).strip():
        issues.append(Issue(LEVEL_WARNING, "브랜드 비어 있음"))
    return TitleResult(
        main_keyword=main,
        title=title,
        tags=tags,
        unconfirmed=list(dict.fromkeys(unconfirmed))[:8],
        issues=issues,
    )


def generate_titles(
    master: pd.DataFrame,
    keyword_tables: dict[str, pd.DataFrame],
    items: dict,
    settings: dict,
    rules: dict,
) -> tuple[pd.DataFrame, list[str]]:
    """마스터 시트의 추천상품명·추천태그·검사결과를 채웁니다. 최종* 칸(사람이 고친 값)은 건드리지 않습니다."""
    out = master.copy()
    skipped = Counter()
    for idx, product in out.iterrows():
        item = product["품목"]
        if not item:
            skipped["품목 없음"] += 1
            continue
        if item not in keyword_tables:
            skipped[f"'{item}' 키워드 조사 안 됨"] += 1
            continue
        result = compose(product.to_dict(), keyword_tables[item], item, items.get(item, {}).get("seeds", []), settings, rules)
        out.at[idx, "메인키워드"] = result.main_keyword
        out.at[idx, "추천상품명"] = result.title
        out.at[idx, "추천태그"] = ",".join(result.tags)
        out.at[idx, "확인필요속성"] = ", ".join(result.unconfirmed)

        final_title = product["최종상품명"] or result.title
        issues = result.issues + check_title(final_title, rules, settings)
        out.at[idx, "검사결과"] = "; ".join(map(str, issues)) or "통과"

    notes = [f"상품명 생성 {len(out) - sum(skipped.values())}개"]
    notes += [f"건너뜀 — {reason}: {n}개" for reason, n in skipped.items()]
    errors = out["검사결과"].str.contains(LEVEL_ERROR).sum()
    if errors:
        notes.append(f"검사 오류가 있는 상품 {errors}개 — '검사결과' 칸을 확인하세요.")
    return out, notes
