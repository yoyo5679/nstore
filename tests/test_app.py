"""화면(app.py)이 오류 없이 뜨는지 확인."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from nstore import config

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def test_app_renders_without_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MASTER_PATH", tmp_path / "master.xlsx")
    monkeypatch.setattr(config, "KEYWORDS_PATH", tmp_path / "keywords.xlsx")
    at = AppTest.from_file(APP).run(timeout=30)
    assert not at.exception
    assert [t.label for t in at.tabs] == ["1. 아임웹 가져오기", "2. 키워드 조사", "3. 상품명·태그", "4. 스마트스토어 엑셀"]


def test_app_renders_with_results(tmp_path, monkeypatch):
    import pandas as pd
    from fakes import walker_scenario

    from nstore import pipeline

    for name, file in [("MASTER_PATH", "master.xlsx"), ("KEYWORDS_PATH", "keywords.xlsx"),
                       ("CACHE_PATH", "cache.sqlite"), ("SMARTSTORE_OUTPUT_PATH", "upload.xlsx")]:
        monkeypatch.setattr(config, name, tmp_path / file)
    searchad, shopping = walker_scenario()
    monkeypatch.setattr(pipeline.SearchAdClient, "from_env", classmethod(lambda cls, cache=None: searchad))
    monkeypatch.setattr(pipeline.ShoppingClient, "from_env", classmethod(lambda cls, cache=None: shopping))
    imweb = tmp_path / "imweb.xlsx"
    pd.DataFrame({"상품코드": ["A1"], "상품명": ["접이식 성인용 보행기"], "브랜드": ["케어메이트"]}).to_excel(imweb, index=False)
    pipeline.run_import(imweb)
    pipeline.run_keywords()
    pipeline.run_titles()

    at = AppTest.from_file(APP).run(timeout=30)
    assert not at.exception
    assert len(at.dataframe) == 3  # 마스터, 키워드, 상품명 표


def test_detail_page_edit_and_undo(tmp_path, monkeypatch):
    from fakes import FakeGemini, png_bytes, section

    from nstore.detail import planner
    from nstore.detail.workspace import Workspace

    for name, path in [("MASTER_PATH", tmp_path / "master.xlsx"), ("PRODUCTS_DIR", tmp_path / "products"),
                       ("THEME_PATH", tmp_path / "theme.json"), ("DETAIL_OUTPUT_DIR", tmp_path / "out")]:
        monkeypatch.setattr(config, name, path)
    ws = Workspace("A1").ensure()
    (ws.photos_dir / "front.jpg").write_bytes(png_bytes())
    planner.extract_facts(ws, FakeGemini(), {})
    plan = {"concept": "c", "sections": [section("s01", "hero", "generate"), section("s02", "faq", items=[("Q", "A")])]}
    planner.make_plan(ws, FakeGemini(plan), {}, {}, 6)

    at = AppTest.from_file(APP).run(timeout=30)
    at.switch_page("ui/detail.py").run(timeout=30)
    at.text_input[0].set_value("A1").run(timeout=30)
    assert not at.exception
    assert [t.label for t in at.tabs] == ["① 자료", "② 구성·카피", "③ 이미지", "④ 디자인", "⑤ 내보내기"]

    at.text_area(key="A1:s02:headline").set_value("직접 고친 제목")
    at.button(key="A1:s02:save").click().run(timeout=30)
    assert not at.exception
    assert ws.load_plan().sections[1].headline == "직접 고친 제목"

    at.button(key="A1:s01:down").click().run(timeout=30)
    assert [s.id for s in ws.load_plan().sections] == ["s02", "s01"]

    undo = next(b for b in at.button if b.label.startswith("되돌리기"))
    undo.click().run(timeout=30)
    assert [s.id for s in ws.load_plan().sections] == ["s01", "s02"]
    assert ws.load_plan().sections[1].headline == "직접 고친 제목"
