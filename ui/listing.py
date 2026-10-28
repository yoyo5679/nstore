"""1단계 화면: 아임웹 → 키워드 → 상품명·태그 → 스마트스토어 엑셀"""

from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from nstore import config, pipeline
from nstore.config import ConfigError
from nstore.keywords import load_keyword_tables
from nstore.master import load_master
from nstore.naver import NaverAPIError

st.title("상품명·키워드·등록 엑셀")

EXPECTED_ERRORS = (ConfigError, NaverAPIError, FileExistsError, FileNotFoundError, ValueError)


def show(notes: list[str]) -> None:
    st.success("\n\n".join(notes))


def save_upload(uploaded) -> Path:
    suffix = Path(uploaded.name).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(uploaded.getbuffer())
        return Path(f.name)


def download(path: Path, label: str) -> None:
    if path.exists():
        st.download_button(label, path.read_bytes(), file_name=path.name)


step1, step2, step3, step4 = st.tabs(["1. 아임웹 가져오기", "2. 키워드 조사", "3. 상품명·태그", "4. 스마트스토어 엑셀"])

with step1:
    st.write("아임웹 관리자에서 받은 상품 엑셀(또는 CSV)을 올리면 마스터 시트를 만듭니다.")
    uploaded = st.file_uploader("아임웹 상품 엑셀", type=["xlsx", "xls", "csv"], key="imweb")
    force = st.checkbox("기존 마스터 시트 덮어쓰기 (엑셀에서 고친 내용이 지워집니다)")
    if uploaded and st.button("마스터 시트 만들기"):
        try:
            show(pipeline.run_import(save_upload(uploaded), force))
        except EXPECTED_ERRORS as e:
            st.error(str(e))
    if config.MASTER_PATH.exists():
        master = load_master(config.MASTER_PATH)
        st.caption(f"현재 마스터 시트: 상품 {len(master)}개, 품목 미분류 {(master['품목'] == '').sum()}개")
        st.dataframe(master[["자사몰상품코드", "자사몰상품명", "품목", "품목분류메모", "브랜드", "모델명"]], height=300)
        download(config.MASTER_PATH, "마스터 시트 받기 (품목·브랜드·모델명 채우기)")
    st.write("엑셀에서 고친 마스터 시트를 다시 올리려면:")
    edited = st.file_uploader("수정한 master.xlsx", type=["xlsx"], key="master")
    if edited and st.button("수정본 반영"):
        config.MASTER_PATH.write_bytes(edited.getbuffer())
        st.success("반영했습니다.")

with step2:
    item_specs = config.load_yaml("items.yaml")["items"]
    in_master = []
    if config.MASTER_PATH.exists():
        in_master = sorted({i for i in load_master(config.MASTER_PATH)["품목"] if i})
    chosen = st.multiselect("조사할 품목", list(item_specs), default=in_master)
    st.caption("같은 키워드는 14일간 다시 조회하지 않습니다 (data/cache.sqlite).")
    if st.button("키워드 조사 시작", disabled=not chosen):
        bar = st.progress(0.0)
        try:
            show(pipeline.run_keywords(chosen, progress=lambda f, msg: bar.progress(f, text=msg)))
        except EXPECTED_ERRORS as e:
            st.error(str(e))
    tables = load_keyword_tables(config.KEYWORDS_PATH)
    if tables:
        names = list(tables)
        pick = st.selectbox("결과 보기", names)
        st.dataframe(tables[pick], height=400)
        download(config.KEYWORDS_PATH, "키워드 엑셀 받기 ('구분' 칸 검토)")
        edited_kw = st.file_uploader("수정한 keywords.xlsx", type=["xlsx"], key="kw")
        if edited_kw and st.button("키워드 수정본 반영"):
            config.KEYWORDS_PATH.write_bytes(edited_kw.getbuffer())
            st.success("반영했습니다.")

with step3:
    st.write("키워드 표의 '메인'·'세부'·'연관'으로 상품명과 태그를 만들고 규칙 검사를 합니다.")
    if st.button("상품명·태그 만들기"):
        try:
            show(pipeline.run_titles())
        except EXPECTED_ERRORS as e:
            st.error(str(e))
    if config.MASTER_PATH.exists():
        master = load_master(config.MASTER_PATH)
        only_issues = st.checkbox("검사 오류·주의가 있는 상품만 보기")
        view = master[master["검사결과"].str.contains("오류|주의")] if only_issues else master
        st.dataframe(
            view[["자사몰상품명", "추천상품명", "최종상품명", "추천태그", "확인필요속성", "검사결과"]],
            height=420,
        )
        download(config.MASTER_PATH, "마스터 시트 받기 ('최종상품명' 칸에서 수정)")

with step4:
    st.write("스마트스토어센터 → 상품 일괄등록에서 받은 최신 양식을 올리면 그 양식에 채워 드립니다.")
    template = st.file_uploader("스마트스토어 일괄등록 양식 (.xlsx)", type=["xlsx"], key="template")
    if st.button("스마트스토어 엑셀 만들기"):
        try:
            show(pipeline.run_export(save_upload(template) if template else None))
        except EXPECTED_ERRORS as e:
            st.error(str(e))
    download(config.SMARTSTORE_OUTPUT_PATH, "스마트스토어 업로드 파일 받기")
