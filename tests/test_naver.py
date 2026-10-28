import base64
import hashlib
import hmac

from nstore import naver
from nstore.naver import SearchAdClient, ShoppingClient, clean_title, parse_count, sign


def test_sign_matches_searchad_spec():
    expected = base64.b64encode(
        hmac.new(b"secret", b"1700000000000.GET./keywordstool", hashlib.sha256).digest()
    ).decode()
    assert sign("1700000000000", "GET", "/keywordstool", "secret") == expected


def test_parse_count_handles_low_volume_string():
    assert parse_count("< 10") == 5
    assert parse_count(1234) == 1234
    assert parse_count("1,234") == 1234
    assert parse_count("") == 0


def test_clean_title_strips_bold_and_entities():
    assert clean_title("<b>성인용</b>보행기 &amp; 실버카") == "성인용보행기 & 실버카"


def test_related_keywords_strips_spaces_and_batches_hints(monkeypatch):
    client = SearchAdClient("k", "s", "c")
    seen = []

    def fake_tool(hints):
        seen.append(hints)
        return [{"relKeyword": h, "monthlyPcQcCnt": "< 10", "monthlyMobileQcCnt": 20, "compIdx": "낮음"} for h in hints]

    monkeypatch.setattr(client, "_keywordstool", fake_tool)
    stats = client.related_keywords(["성인용 보행기", "실버카", "a", "b", "c", "d", "실버카"])
    assert seen == [["성인용보행기", "실버카", "a", "b", "c"], ["d"]]
    assert stats[0].keyword == "성인용보행기" and stats[0].volume == 25


def test_shopping_search_parses_items(monkeypatch):
    payload = {
        "total": 1234,
        "items": [{
            "title": "<b>휠체어</b>", "mallName": "몰", "brand": "미키", "maker": "",
            "category1": "생활/건강", "category2": "실버용품", "category3": "휠체어", "category4": "",
        }],
    }
    monkeypatch.setattr(naver, "_get_with_retry", lambda *a, **k: payload)
    result = ShoppingClient("id", "secret").search("휠체어")
    assert result.total == 1234
    assert result.items[0].title == "휠체어"
    assert result.items[0].category == ("생활/건강", "실버용품", "휠체어")
