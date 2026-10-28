"""네트워크 없이 테스트하기 위한 가짜 네이버 클라이언트와 공통 시나리오."""

from __future__ import annotations

from nstore.naver import KeywordStat, ShopItem, ShopResult

SILVER = ("생활/건강", "실버용품", "보행보조용품")
BABY = ("출산/육아", "유아동", "보행기")


class FakeSearchAd:
    def __init__(self, stats: list[KeywordStat]):
        self.stats = stats
        self.calls: list[list[str]] = []

    def related_keywords(self, hints):
        self.calls.append(list(hints))
        return self.stats


class FakeShopping:
    def __init__(self, data: dict[str, tuple[int, list[tuple[tuple[str, ...], str]]]]):
        self.data = data
        self.queries: list[str] = []

    def search(self, query, display=40):
        self.queries.append(query)
        total, items = self.data.get(query, (0, []))
        return ShopResult(
            query=query,
            total=total,
            items=[ShopItem(title="", mall="", brand=brand, maker="", category=cat) for cat, brand in items],
        )


def walker_scenario() -> tuple[FakeSearchAd, FakeShopping]:
    """성인용보행기 품목: 아기 보행기·타사 브랜드 키워드가 섞인 상황."""
    stats = [
        KeywordStat("성인용보행기", 1000, 4000, "중간"),
        KeywordStat("노인보행기", 800, 3200, "중간"),
        KeywordStat("실버카", 500, 2500, "낮음"),
        KeywordStat("보행기", 2000, 8000, "높음"),
        KeywordStat("보행보조차", 200, 600, "낮음"),
        KeywordStat("접이식성인용보행기", 100, 400, "낮음"),
        KeywordStat("성인용보행기추천", 100, 300, "낮음"),
        KeywordStat("경량성인용보행기", 50, 250, "낮음"),
        KeywordStat("케어라인보행기", 100, 200, "낮음"),
        KeywordStat("보행기바퀴", 5, 5, "낮음"),
    ]
    silver = [(SILVER, "케어라인")] * 4 + [(SILVER, "케어메이트")] * 4 + [(BABY, "")] * 2
    data = {kw: (3000, silver) for kw in [
        "성인용보행기", "노인보행기", "실버카", "보행보조차", "접이식성인용보행기",
        "성인용보행기추천", "경량성인용보행기", "케어라인보행기",
    ]}
    data["보행기"] = (90000, [(BABY, "")] * 9 + [(SILVER, "")])
    return FakeSearchAd(stats), FakeShopping(data)


WALKER_SEEDS = ["성인용보행기", "노인보행기", "실버카"]
