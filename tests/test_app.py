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
