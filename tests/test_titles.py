import pandas as pd
from fakes import WALKER_SEEDS, walker_scenario

from nstore.keywords import research_item
from nstore.titles import check_title, compose, generate_titles

PRODUCT = {
    "브랜드": "케어메이트",
    "모델명": "CM-200",
    "자사몰상품명": "케어메이트 접이식 성인용 보행기 CM-200",
    "상세설명원본": "",
}


def walker_table(settings):
    searchad, shopping = walker_scenario()
    return research_item("성인용보행기", WALKER_SEEDS, searchad, shopping, settings, {"케어메이트"}).table


def test_compose_uses_only_confirmed_modifiers(settings, rules):
    result = compose(PRODUCT, walker_table(settings), "성인용보행기", WALKER_SEEDS, settings, rules)
    assert result.title == "케어메이트 CM-200 접이식 성인용보행기"
    assert result.unconfirmed == ["경량"]  # 상품 정보에 없는 속성은 넣지 않고 알려줌
    assert result.tags == ["노인보행기", "실버카", "보행보조차"]  # 동의어는 태그로, 추천·타사·미확인 제외
    assert result.issues == []


def test_compose_trims_modifiers_to_recommended_length(settings, rules):
    product = dict(PRODUCT, 모델명="CM-200 프리미엄 스페셜 에디션 그레이 라지 사이즈 4륜형")
    result = compose(product, walker_table(settings), "성인용보행기", WALKER_SEEDS, settings, rules)
    assert "접이식" not in result.title
    assert result.title.endswith("성인용보행기")


def test_check_title_rules(settings, rules):
    issues = [str(i) for i in check_title("무료 배송 케어메이트 보행기★ 보행기 치료", rules, settings)]
    assert "오류: 금지 문구 '무료배송'" in issues
    assert "주의: 특수문자 ★" in issues
    assert "주의: 같은 단어 반복: 보행기" in issues
    assert "주의: 확인 필요 표현 '치료'" in issues
    assert check_title("케어메이트 CM-200 접이식 성인용보행기", rules, settings) == []


def test_check_title_blocks_copay_discount(settings, rules):
    issues = check_title("성인용보행기 본인부담금 할인", rules, settings)
    assert any(i.level == "오류" and "본인부담금할인" in i.message for i in issues)


def test_generate_titles_keeps_manual_final_title(settings, rules):
    master = pd.DataFrame([
        dict(PRODUCT, 품목="성인용보행기", 최종상품명="", 옵션="", 요약설명=""),
        dict(PRODUCT, 품목="성인용보행기", 최종상품명="케어메이트 보행기 무료배송", 옵션="", 요약설명=""),
        dict(PRODUCT, 품목="", 최종상품명="", 옵션="", 요약설명=""),
    ])
    for col in ["메인키워드", "추천상품명", "추천태그", "확인필요속성", "검사결과"]:
        master[col] = ""
    out, notes = generate_titles(master, {"성인용보행기": walker_table(settings)}, {}, settings, rules)
    assert out.loc[0, "검사결과"] == "통과"
    assert out.loc[1, "최종상품명"] == "케어메이트 보행기 무료배송"
    assert "금지 문구 '무료배송'" in out.loc[1, "검사결과"]
    assert out.loc[2, "추천상품명"] == ""
    assert "건너뜀 — 품목 없음: 1개" in notes
