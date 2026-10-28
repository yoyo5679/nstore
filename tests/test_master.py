import pandas as pd

from nstore import config
from nstore.excel_io import find_header_row, match_columns, read_table
from nstore.master import build_master, classify_item

ITEMS = config.load_yaml("items.yaml")["items"]


def test_classify_item_picks_longest_alias():
    assert classify_item("케어메이트 접이식 성인용 보행기 CM-200", ITEMS) == ("성인용보행기", "")
    assert classify_item("욕창예방 매트리스 에어매트 3단", ITEMS)[0] == "욕창예방매트리스"
    assert classify_item("욕창방지방석 휠체어용", ITEMS)[0] == "욕창예방방석"


def test_classify_item_flags_ties_and_misses():
    item, memo = classify_item("휠체어 경사로 2단", ITEMS)
    assert item == "" and "경사로" in memo and "수동휠체어" in memo
    assert classify_item("알 수 없는 상품", ITEMS) == ("", "품목 자동분류 실패")


def test_header_detection_skips_title_rows():
    rows = [["상품 목록"], ["", ""], ["상품번호", "상품명", "판매가"], ["1", "a", "100"]]
    assert find_header_row(rows, ["상품명", "판매가"]) == 2


def test_match_columns_ignores_spaces_and_required_marks():
    mapping = match_columns(["상품 명*", "판매 가격"], {"자사몰상품명": ["상품명"], "판매가": ["판매가", "판매가격"]})
    assert mapping == {"자사몰상품명": "상품 명*", "판매가": "판매 가격"}


def test_read_table_csv_cp949(tmp_path):
    path = tmp_path / "imweb.csv"
    path.write_bytes("상품코드,상품명\nP1,성인용보행기\n".encode("cp949"))
    table = read_table(path, ["상품코드", "상품명"])
    assert table.to_dict("records") == [{"상품코드": "P1", "상품명": "성인용보행기"}]


def test_build_master_from_imweb_excel(tmp_path):
    path = tmp_path / "imweb.xlsx"
    pd.DataFrame({
        "상품번호": ["001", "002"],
        "상품명": ["케어메이트 접이식 성인용보행기", "정체불명 상품"],
        "판매가": ["150000", "9000"],
        "상세설명": ["<p>접이식&nbsp;<b>경량</b></p>", ""],
    }).to_excel(path, index=False)

    master, notes = build_master(path)
    assert master["자사몰상품코드"].tolist() == ["001", "002"]  # 앞자리 0 유지
    assert master["품목"].tolist() == ["성인용보행기", ""]
    assert master.loc[0, "상세설명원본"] == "접이식 경량"
    assert any("품목을 정하지 못한 상품 1개" in n for n in notes)
    assert any("못 찾은 칸" in n and "브랜드" in n for n in notes)
