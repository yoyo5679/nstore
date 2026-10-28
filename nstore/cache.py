"""네이버 API 응답 캐시.

상품 400개가 같은 품목 키워드를 공유하므로, 한 번 조회한 키워드는 일정 기간 다시 부르지 않습니다.
(쇼핑 검색 API는 하루 호출 한도가 있습니다.)
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class Cache:
    def __init__(self, path: Path, ttl_days: float):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cache ("
            " namespace TEXT, key TEXT, value TEXT, saved_at REAL,"
            " PRIMARY KEY (namespace, key))"
        )
        self._ttl = ttl_days * 86400

    def get(self, namespace: str, key: str) -> Any | None:
        row = self._conn.execute(
            "SELECT value, saved_at FROM cache WHERE namespace = ? AND key = ?",
            (namespace, key),
        ).fetchone()
        if row is None or time.time() - row[1] > self._ttl:
            return None
        return json.loads(row[0])

    def set(self, namespace: str, key: str, value: Any) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO cache VALUES (?, ?, ?, ?)",
            (namespace, key, json.dumps(value, ensure_ascii=False), time.time()),
        )
        self._conn.commit()
