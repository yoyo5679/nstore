"""브라우저 화면.  실행: streamlit run app.py"""

import streamlit as st

st.set_page_config(page_title="스마트스토어 상품 등록", layout="wide")
st.navigation([
    st.Page("ui/listing.py", title="1단계 · 상품명·등록 엑셀", default=True),
    st.Page("ui/detail.py", title="2단계 · 상세페이지"),
]).run()
