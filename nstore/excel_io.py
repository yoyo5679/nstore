"""엑셀/CSV 읽기 공통 도구.

아임웹·스마트스토어 엑셀은 헤더가 첫 줄이 아니거나 이름이 조금씩 다를 수 있어서,
헤더 행을 찾아내고 이름을 느슨하게 비교합니다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

_REQUIRED_MARK = re.compile(r"\(필수\)|\[필수\]|\*")
_SPACES = re.compile(r"\s+")


def normalize_header(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = _REQUIRED_MARK.sub("", str(value))
    return _SPACES.sub("", text).lower()


def find_header_row(rows: list[list], expected: Iterable[str], scan: int = 15) -> int | None:
    """앞쪽 행 중에서 기대하는 헤더 이름이 가장 많이 들어 있는 행 번호."""
    expected_norm = {normalize_header(e) for e in expected} - {""}
    best, best_hits = None, 0
    for i, row in enumerate(rows[:scan]):
        hits = sum(1 for v in row if normalize_header(v) in expected_norm)
        if hits > best_hits:
            best, best_hits = i, hits
    return best


def match_columns(columns: Iterable[str], candidates: dict[str, list[str]]) -> dict[str, str]:
    """{마스터 컬럼: 원본 컬럼}. 후보 목록에서 먼저 맞는 이름을 씁니다."""
    by_norm: dict[str, str] = {}
    for col in columns:
        by_norm.setdefault(normalize_header(col), col)
    result = {}
    for field, names in candidates.items():
        for name in names:
            col = by_norm.get(normalize_header(name))
            if col is not None:
                result[field] = col
                break
    return result


def _read_raw(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        for encoding in ("utf-8-sig", "cp949"):
            try:
                return pd.read_csv(path, header=None, dtype=str, encoding=encoding)
            except UnicodeDecodeError:
                continue
        raise ValueError(f"{path.name}: 인코딩을 알 수 없습니다 (UTF-8, CP949 아님)")
    return pd.read_excel(path, header=None, dtype=str)


def read_table(path: Path, expected_headers: Iterable[str]) -> pd.DataFrame:
    """헤더 행을 자동으로 찾아 표로 읽습니다. 모든 값은 문자열, 빈칸은 ''."""
    raw = _read_raw(Path(path)).fillna("")
    header_idx = find_header_row(raw.values.tolist(), expected_headers) or 0

    headers, seen = [], {}
    for value in raw.iloc[header_idx]:
        name = str(value).strip() or "컬럼"
        seen[name] = seen.get(name, 0) + 1
        headers.append(name if seen[name] == 1 else f"{name}_{seen[name]}")

    table = raw.iloc[header_idx + 1 :].copy()
    table.columns = headers
    table = table[(table != "").any(axis=1)]
    return table.reset_index(drop=True)
