"""상세페이지 데이터 구조.

Claude에게 이 구조 그대로 JSON을 받도록 요청하므로(구조화 출력), 필드에 기본값을 두지 않습니다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

SECTION_TYPES = ["hero", "problem", "solution", "feature", "trust", "usage", "faq", "spec", "caution", "cta"]  # SectionType 과 같게
SECTION_LABELS = {
    "hero": "첫 화면",
    "problem": "고민 공감",
    "solution": "해결 제시",
    "feature": "특징",
    "trust": "신뢰",
    "usage": "사용법",
    "faq": "자주 묻는 질문",
    "spec": "제품 정보",
    "caution": "주의사항",
    "cta": "마무리",
}
IMAGE_MODES = ["photo", "generate", "none"]
# scene: 사용 장면 / detail: 디테일 컷 / cutout: 흰 배경 누끼 / extend: 실사진 배경 확장
IMAGE_KINDS = ["scene", "detail", "cutout", "extend"]


class Spec(BaseModel):
    name: str
    value: str


class Feature(BaseModel):
    title: str
    detail: str
    source: str  # 근거 자료 (파일명·페이지)


class Facts(BaseModel):
    """카탈로그·설명서에서 뽑은 사실. 카피는 이 안의 내용만 씁니다."""

    product_name: str
    one_line: str
    manufacturer: str
    target_users: list[str]
    features: list[Feature]
    specs: list[Spec]
    components: list[str]
    usage_steps: list[str]
    cautions: list[str]
    certifications: list[str]
    unknowns: list[str]  # 자료에서 확인하지 못한 것


class ReviewInsights(BaseModel):
    selling_points: list[str]  # 고객이 좋다고 한 점
    complaints: list[str]  # 불만 — 반박처리 재료
    questions: list[str]  # 구매 전 망설임·질문


class Item(BaseModel):
    title: str
    text: str


class ImageSpec(BaseModel):
    mode: str  # photo | generate | none
    photo: str  # mode=photo: 실사진 파일명 / kind=extend: 확장할 실사진
    kind: str  # mode=generate: scene | detail | cutout | extend
    prompt: str  # mode=generate: 원하는 장면 설명 (한국어). 실제 이미지 프롬프트는 생성 직전에 Claude가 씀


class Section(BaseModel):
    id: str
    type: str
    role: str  # 후킹 / 공감 / 해결 / 신뢰 / 반박처리 / 정보 / 행동유도
    eyebrow: str
    headline: str
    body: str
    items: list[Item]
    image: ImageSpec


class Plan(BaseModel):
    concept: str
    sections: list[Section]


# 페이지 배치 선택지 (디자인 탭·레퍼런스 분석 공통)
LAYOUT_OPTIONS = {
    "align": {"center": "가운데 정렬", "left": "왼쪽 정렬"},
    "hero": {"stacked": "글 아래 사진", "overlay": "사진 위에 글"},
    "image_style": {"rounded": "여백 + 둥근 사진", "full": "화면 끝까지 꽉 찬 사진"},
    "sections": {"alternate": "섹션마다 배경 번갈아", "plain": "배경 하나로 통일"},
}


class Theme(BaseModel):
    """페이지 디자인. 배치 항목은 예전에 저장한 theme.json 도 읽히도록 기본값을 둡니다."""

    primary: str
    accent: str
    background: str
    surface: str
    text: str
    muted: str
    font: str  # gothic | serif
    radius: int
    mood: str
    align: str = "center"
    hero: str = "stacked"
    image_style: str = "rounded"
    sections: str = "alternate"


class ReferenceGuide(BaseModel):
    """레퍼런스에서 따라 할 기획·말투·사진 분위기. 내용·문장·사진 자체는 베끼지 않습니다."""

    section_flow: list[str]  # 섹션 흐름 (우리 섹션 종류 이름: hero, problem …)
    copy_tone: str  # 말투, 문장 길이, 헤드라인 방식
    photo_style: str  # 사진 분위기 (조명, 배경, 인물, 색감, 구도)
    notes: list[str]  # 그 밖에 따라 하면 좋은 점


SectionType = Literal["hero", "problem", "solution", "feature", "trust", "usage", "faq", "spec", "caution", "cta"]


class ReferenceAnalysis(BaseModel):
    """레퍼런스 분석 결과 (Claude 구조화 출력용 — 기본값 없음, 선택지는 정해진 값만 나오게 Literal)."""

    primary: str
    accent: str
    background: str
    surface: str
    text: str
    muted: str
    font: Literal["gothic", "serif"]
    radius: int
    mood: str
    align: Literal["center", "left"]
    hero: Literal["stacked", "overlay"]
    image_style: Literal["rounded", "full"]
    sections: Literal["alternate", "plain"]
    section_flow: list[SectionType]
    copy_tone: str
    photo_style: str
    notes: list[str]


class ImagePrompt(BaseModel):
    prompt: str  # Gemini 이미지 모델에 보낼 영어 프롬프트
