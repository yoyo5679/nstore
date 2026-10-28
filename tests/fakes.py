"""네트워크 없이 테스트하기 위한 가짜 네이버 클라이언트와 공통 시나리오."""

from __future__ import annotations

import io

from PIL import Image

from nstore.detail.schema import Facts, Plan, ReviewInsights, Section, Theme
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


# ---------------------------------------------------------------- 2단계: 가짜 Gemini


def png_bytes(color="#88AA99", size=(400, 300)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


SAMPLE_FACTS = {
    "product_name": "케어메이트 CM-200", "one_line": "접이식 성인용보행기", "manufacturer": "케어메이트(주)",
    "target_users": ["보행이 불편한 어르신"],
    "features": [{"title": "접이식", "detail": "한 번에 접힘", "source": "catalog.pdf p2"}],
    "specs": [{"name": "무게", "value": "6.8kg"}, {"name": "최대 하중", "value": "100kg"}],
    "components": ["본체"], "usage_steps": ["펴기"], "cautions": ["앉기 전 브레이크"],
    "certifications": [], "unknowns": [],
}


def section(sid, stype="feature", mode="none", photo="", kind="scene", headline="제목", body="", items=()):
    return {"id": sid, "type": stype, "role": "해결", "eyebrow": "", "headline": headline, "body": body,
            "items": [{"title": t, "text": x} for t, x in items],
            "image": {"mode": mode, "photo": photo, "kind": kind, "prompt": "walking in park"}}


class FakeGemini:
    def __init__(self, plan: dict | None = None):
        self.plan = plan or {"concept": "든든한 산책", "sections": [section("s01", "hero", "generate")]}
        self.json_calls: list[tuple[str, type, list]] = []
        self.image_calls: list[tuple[str, list, str | None]] = []

    def json(self, prompt, schema, files=(), system=None):
        self.json_calls.append((prompt, schema, list(files)))
        if schema is Facts:
            return Facts.model_validate(SAMPLE_FACTS)
        if schema is ReviewInsights:
            return ReviewInsights(selling_points=["가벼움"], complaints=["바퀴 소음"], questions=["접은 크기?"])
        if schema is Plan:
            return Plan.model_validate(self.plan)
        if schema is Section:
            return Section.model_validate(section("바뀐id", "hero", headline="고친 헤드라인"))
        if schema is Theme:
            return Theme(primary="#123456", accent="xx", background="#FFFFFF", surface="#F0F0F0",
                         text="#111111", muted="#666666", font="handwriting", radius=99, mood="차분함")
        raise AssertionError(schema)

    def image(self, prompt, references=(), aspect_ratio=None):
        self.image_calls.append((prompt, list(references), aspect_ratio))
        return png_bytes()
