"""네이버 API 클라이언트.

- SearchAdClient : 검색광고 API 키워드 도구 (연관키워드, 월간 검색수, 광고 경쟁정도)
- ShoppingClient : 개발자센터 쇼핑 검색 API (등록 상품 수, 상위 상품의 카테고리·브랜드)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import re
import time
from dataclasses import dataclass

import requests

from .cache import Cache
from .config import require_env

RETRY_STATUS = {429, 500, 502, 503, 504}


class NaverAPIError(RuntimeError):
    pass


def _get_with_retry(session: requests.Session, url: str, *, params: dict, headers: dict) -> dict:
    delay = 1.0
    for attempt in range(4):
        resp = session.get(url, params=params, headers=headers, timeout=20)
        if resp.status_code not in RETRY_STATUS or attempt == 3:
            break
        time.sleep(delay)
        delay *= 2
    if resp.status_code != 200:
        raise NaverAPIError(f"{url} 호출 실패 ({resp.status_code}): {resp.text[:300]}")
    return resp.json()


class _Throttle:
    def __init__(self, min_interval: float):
        self._min_interval = min_interval
        self._last = 0.0

    def wait(self) -> None:
        gap = time.monotonic() - self._last
        if gap < self._min_interval:
            time.sleep(self._min_interval - gap)
        self._last = time.monotonic()


# ---------------------------------------------------------------- 검색광고 API


@dataclass
class KeywordStat:
    keyword: str
    pc: int
    mobile: int
    ad_competition: str  # 높음 / 중간 / 낮음

    @property
    def volume(self) -> int:
        return self.pc + self.mobile


def parse_count(value) -> int:
    """검색수 값 정리. 검색이 아주 적으면 API가 숫자 대신 '< 10' 문자열을 줍니다."""
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if text.startswith("<"):
        return 5
    try:
        return int(float(text.replace(",", "")))
    except ValueError:
        return 0


def sign(timestamp: str, method: str, uri: str, secret_key: str) -> str:
    message = f"{timestamp}.{method}.{uri}"
    digest = hmac.new(secret_key.encode(), message.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


class SearchAdClient:
    BASE_URL = "https://api.searchad.naver.com"
    MAX_HINTS = 5  # keywordstool 한 번에 넣을 수 있는 씨앗 키워드 수

    def __init__(self, api_key: str, secret_key: str, customer_id: str, cache: Cache | None = None):
        self._api_key = api_key
        self._secret_key = secret_key
        self._customer_id = customer_id
        self._cache = cache
        self._session = requests.Session()
        self._throttle = _Throttle(0.3)

    @classmethod
    def from_env(cls, cache: Cache | None = None) -> "SearchAdClient":
        return cls(
            require_env("NAVER_AD_API_KEY"),
            require_env("NAVER_AD_SECRET_KEY"),
            require_env("NAVER_AD_CUSTOMER_ID"),
            cache,
        )

    def _headers(self, method: str, uri: str) -> dict:
        timestamp = str(int(time.time() * 1000))
        return {
            "X-Timestamp": timestamp,
            "X-API-KEY": self._api_key,
            "X-Customer": str(self._customer_id),
            "X-Signature": sign(timestamp, method, uri, self._secret_key),
        }

    def _keywordstool(self, hints: list[str]) -> list[dict]:
        key = ",".join(sorted(hints))
        if self._cache and (cached := self._cache.get("keywordstool", key)) is not None:
            return cached
        self._throttle.wait()
        uri = "/keywordstool"
        data = _get_with_retry(
            self._session,
            self.BASE_URL + uri,
            params={"hintKeywords": ",".join(hints), "showDetail": "1"},
            headers=self._headers("GET", uri),
        )
        rows = data.get("keywordList", [])
        if self._cache:
            self._cache.set("keywordstool", key, rows)
        return rows

    def related_keywords(self, hints: list[str]) -> list[KeywordStat]:
        """씨앗 키워드의 연관키워드와 검색수. 씨앗 키워드 자신도 결과에 포함됩니다."""
        # 키워드 도구는 띄어쓰기가 들어간 키워드를 받지 않습니다.
        cleaned = list(dict.fromkeys(h.replace(" ", "") for h in hints if h.strip()))
        stats: dict[str, KeywordStat] = {}
        for i in range(0, len(cleaned), self.MAX_HINTS):
            for row in self._keywordstool(cleaned[i : i + self.MAX_HINTS]):
                stat = KeywordStat(
                    keyword=row["relKeyword"],
                    pc=parse_count(row.get("monthlyPcQcCnt", 0)),
                    mobile=parse_count(row.get("monthlyMobileQcCnt", 0)),
                    ad_competition=row.get("compIdx", ""),
                )
                stats[stat.keyword] = stat
        return list(stats.values())


# ---------------------------------------------------------------- 쇼핑 검색 API

_TAG_RE = re.compile(r"<[^>]+>")


def clean_title(text: str) -> str:
    return html.unescape(_TAG_RE.sub("", text or "")).strip()


@dataclass
class ShopItem:
    title: str
    mall: str
    brand: str
    maker: str
    category: tuple[str, ...]


@dataclass
class ShopResult:
    query: str
    total: int
    items: list[ShopItem]


class ShoppingClient:
    URL = "https://openapi.naver.com/v1/search/shop.json"

    def __init__(self, client_id: str, client_secret: str, cache: Cache | None = None):
        self._headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
        self._cache = cache
        self._session = requests.Session()
        self._throttle = _Throttle(0.12)

    @classmethod
    def from_env(cls, cache: Cache | None = None) -> "ShoppingClient":
        return cls(require_env("NAVER_CLIENT_ID"), require_env("NAVER_CLIENT_SECRET"), cache)

    def search(self, query: str, display: int = 40) -> ShopResult:
        key = f"{query}|{display}"
        data = self._cache.get("shop", key) if self._cache else None
        if data is None:
            self._throttle.wait()
            data = _get_with_retry(
                self._session,
                self.URL,
                params={"query": query, "display": display, "start": 1, "sort": "sim"},
                headers=self._headers,
            )
            if self._cache:
                self._cache.set("shop", key, data)
        items = [
            ShopItem(
                title=clean_title(it.get("title", "")),
                mall=it.get("mallName", ""),
                brand=it.get("brand", ""),
                maker=it.get("maker", ""),
                category=tuple(
                    c for c in (it.get(f"category{n}", "") for n in range(1, 5)) if c
                ),
            )
            for it in data.get("items", [])
        ]
        return ShopResult(query=query, total=int(data.get("total", 0)), items=items)
