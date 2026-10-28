from fakes import SILVER, WALKER_SEEDS, walker_scenario

from nstore.keywords import load_keyword_tables, research_item, save_keyword_tables


def research(settings):
    searchad, shopping = walker_scenario()
    return research_item("성인용보행기", WALKER_SEEDS, searchad, shopping, settings, own_brands={"케어메이트"})


def roles(result):
    return dict(zip(result.table["키워드"], result.table["구분"]))


def test_target_category_comes_from_seed_results(settings):
    assert research(settings).target_category == SILVER


def test_roles_and_exclusions(settings):
    result = research(settings)
    r = roles(result)
    assert result.main_keywords == ["성인용보행기", "노인보행기", "실버카"]
    assert r["보행기"] == "제외"            # 아기 보행기 카테고리
    assert r["케어라인보행기"] == "제외"     # 타사 브랜드
    assert r["접이식성인용보행기"] == "세부"
    assert r["경량성인용보행기"] == "세부"
    assert r["보행보조차"] == "연관"
    assert "보행기바퀴" not in r           # 검색수 미달


def test_notes_explain_exclusions(settings):
    table = research(settings).table.set_index("키워드")
    assert table.loc["보행기", "비고"] == "카테고리 불일치"
    assert table.loc["케어라인보행기", "비고"] == "타사 브랜드 포함(케어라인)"
    assert table.loc["실버카", "경쟁강도"] == round(3000 / 3000, 2)


def test_save_and_reload_keeps_other_items(tmp_path, settings):
    path = tmp_path / "keywords.xlsx"
    save_keyword_tables([research(settings)], path)
    tables = load_keyword_tables(path)
    assert set(tables) == {"요약", "성인용보행기"}

    # 다른 품목만 다시 조사해도 기존 시트와 추천카테고리는 남아야 함
    other = research(settings)
    other.item = "실버카테스트"
    save_keyword_tables([other], path, tables)
    tables = load_keyword_tables(path)
    assert set(tables) == {"요약", "성인용보행기", "실버카테스트"}
    summary = tables["요약"].set_index("품목")
    assert summary.loc["성인용보행기", "추천카테고리"] == " > ".join(SILVER)
