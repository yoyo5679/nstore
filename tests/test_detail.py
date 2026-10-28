import os

import pytest
from fakes import SAMPLE_FACTS, FakeGemini, png_bytes, section

from nstore import config
from nstore.detail import compliance, images, planner, render, theme
from nstore.detail.schema import Facts, Plan
from nstore.detail.workspace import Workspace

SETTINGS = config.load_yaml("settings.yaml")
RULES = config.load_yaml("title_rules.yaml")


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PRODUCTS_DIR", tmp_path / "products")
    monkeypatch.setattr(config, "DETAIL_OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(config, "THEME_PATH", tmp_path / "theme.json")
    w = Workspace("A/1").ensure()
    for name in ("front.jpg", "side.jpg", "back.jpg", "top.jpg"):
        (w.photos_dir / name).write_bytes(png_bytes())
    (w.docs_dir / "catalog.pdf").write_bytes(b"%PDF-1.4")
    return w


def test_workspace_code_is_folder_safe(ws):
    assert ws.code == "A_1"
    assert [p.name for p in ws.photos()] == ["back.jpg", "front.jpg", "side.jpg", "top.jpg"]


def test_extract_facts_sends_docs_and_photos(ws):
    client = FakeGemini()
    facts = planner.extract_facts(ws, client, {"브랜드": "케어메이트"})
    assert ws.load_facts() == facts
    _, _, files = client.json_calls[0]
    assert files[0].name == "catalog.pdf" and len(files) == 5


def test_extract_facts_needs_material(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PRODUCTS_DIR", tmp_path)
    with pytest.raises(ValueError):
        planner.extract_facts(Workspace("empty"), FakeGemini(), {})


def test_make_plan_normalizes_ai_output(ws):
    raw = {"concept": "c", "sections": [
        section("s01", "hero", "generate"),
        section("s01", "feature", "photo", photo="없는사진.jpg"),
        section("", "weird", "generate", kind="painting"),
        section("s04", "usage", "generate"),
    ]}
    planner.extract_facts(ws, FakeGemini(), {})
    (ws.dir / "reviews.txt").write_text("가벼워서 좋아요", encoding="utf-8")
    client = FakeGemini(raw)
    plan = planner.make_plan(ws, client, {"의료기기여부": ""}, {"main": "성인용보행기", "tags": []}, max_generate=2)

    assert [s.id for s in plan.sections] == ["s01", "s02", "s03", "s04"]
    assert plan.sections[1].image.photo == "back.jpg"          # 없는 사진 → 첫 사진
    assert plan.sections[2].type == "solution" and plan.sections[2].image.kind == "scene"
    assert plan.sections[3].image.mode == "photo"              # 생성 한도(2장) 초과분은 실사진으로
    assert ws.load_reviews().complaints == ["바퀴 소음"]       # 리뷰가 있으면 먼저 분석
    assert "성인용보행기" in client.json_calls[-1][0]          # 키워드가 기획 지시에 들어감
    assert ws.history() == ["AI 구성·카피 생성"]


def test_medical_product_prompt_uses_approved_copy(ws):
    planner.extract_facts(ws, FakeGemini(), {})
    ws.save_text("approved_copy.txt", "심의 받은 문장입니다.")
    client = FakeGemini()
    planner.make_plan(ws, client, {"의료기기여부": "Y"}, {}, 6)
    prompt = client.json_calls[-1][0]
    assert "심의 받은 문구에 있는 문장만" in prompt and "심의 받은 문장입니다." in prompt


def test_edit_section_changes_only_that_section_and_undo(ws):
    planner.extract_facts(ws, FakeGemini(), {})
    plan = planner.make_plan(ws, FakeGemini({"concept": "c", "sections": [section("s01", "hero"), section("s02")]}), {}, {}, 6)
    updated = planner.edit_section(ws, FakeGemini(), plan, "s02", "더 짧게", {})
    assert [s.id for s in updated.sections] == ["s01", "s02"]
    assert updated.sections[1].type == "feature"               # AI가 바꾼 id·type은 원래대로
    assert updated.sections[1].headline == "고친 헤드라인"
    assert updated.sections[0].headline == "제목"
    assert ws.undo().sections[1].headline == "제목"
    assert ws.undo() is None                                    # 첫 버전보다 더 뒤로는 못 감


def test_compliance_findings(ws):
    facts = Facts.model_validate(SAMPLE_FACTS)
    plan = Plan.model_validate({"concept": "c", "sections": [
        section("s01", "hero", headline="최대 하중 120kg", body="무게 6.8kg, 본인부담금 할인"),
        section("s02", "usage", items=[("STEP 1", "펴세요")]),
    ]})
    found = [str(f) for f in compliance.check_plan(plan, facts, RULES, {}, "")]
    assert "[s01] 주의: 자료에 없는 숫자 '120' — 사실인지 확인하세요" in found
    assert not any("'6.8'" in f for f in found)
    assert any("금지 문구 '본인부담금할인'" in f for f in found)
    assert not any(f.startswith("[s02]") for f in found)       # STEP 번호는 검사 안 함


def test_compliance_medical(ws):
    plan = Plan.model_validate({"concept": "c", "sections": [section("s01", headline="심의 받은 문장입니다", body="새로 지어낸 문장이에요")]})
    no_copy = compliance.check_plan(plan, None, RULES, {"의료기기여부": "Y"}, "")
    assert no_copy[0].level == "오류" and "심의" in no_copy[0].message
    with_copy = [str(f) for f in compliance.check_plan(plan, None, RULES, {"의료기기여부": "Y"}, "심의 받은 문장입니다.")]
    assert with_copy == ["[s01] 주의: 심의 문구에 없는 문장: 새로 지어낸 문장이에요"]


def test_generate_images_uses_photos_as_reference_and_keeps_history(ws):
    plan = Plan.model_validate({"concept": "c", "sections": [
        section("s01", "hero", "generate", photo="side.jpg"),
        section("s02", "feature", "generate", photo="top.jpg", kind="extend"),
        section("s03", "spec", "photo", photo="front.jpg"),
    ]})
    client = FakeGemini()
    images.generate_missing(ws, client, plan, SETTINGS)
    (p1, refs1, ratio1), (p2, refs2, _) = client.image_calls
    assert [r.name for r in refs1] == ["side.jpg", "back.jpg", "front.jpg"] and ratio1 == "4:5"
    assert "Do not add any text" in p1
    assert [r.name for r in refs2] == ["top.jpg"] and p2.startswith("Extend the background")
    assert images.generate_missing(ws, client, plan, SETTINGS) == ["새로 만들 이미지가 없습니다."]

    images.edit_section_image(ws, client, plan.sections[0], "배경을 거실로", SETTINGS)
    assert client.image_calls[-1][1][0] == ws.section_image("s01")  # 지금 이미지를 고침
    assert ws.has_image_history("s01") and ws.undo_section_image("s01")


def test_theme_from_brand_color_and_sanitize():
    t = theme.from_brand_color("#2f6b5e", "serif", 12)
    assert t.primary == "#2F6B5E" and t.font == "serif" and t.surface.startswith("#")
    assert theme.on_color("#2F6B5E") == "#FFFFFF" and theme.on_color("#FFE14D") == "#17191C"
    fixed = theme.from_reference(FakeGemini(), [])
    assert fixed.accent.startswith("#") and fixed.font == "gothic" and fixed.radius == 40
    with pytest.raises(ValueError):
        theme.from_brand_color("green")


def test_render_html(ws):
    plan = Plan.model_validate({"concept": "c", "sections": [
        section("s01", "hero", "generate", headline="첫 줄\\n둘째 줄"),
        section("s02", "feature", "photo", photo="front.jpg", body="<script>x</script>"),
        section("s03", "faq", items=[("Q1", "A1")]),
    ]})
    html = render.render_html(plan, None, ws, {"제조사": "케어메이트(주)", "광고심의번호": "2026-1234"}, SETTINGS, 860)
    assert "첫 줄<br>둘째 줄" in html
    assert "AI 이미지 생성 전" in html                         # 아직 안 만든 이미지 자리
    assert "POINT 01" in html
    assert "data:image/jpeg;base64," in html
    assert "<script>x</script>" not in html and "&lt;script&gt;" in html
    assert "의료기기 광고심의필: 2026-1234" in html


def _browser_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch(executable_path=os.environ.get("NSTORE_CHROMIUM") or None).close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _browser_available(), reason="브라우저 없음 (playwright install chromium)")
def test_export_platform_widths(ws):
    from PIL import Image

    plan = Plan.model_validate({"concept": "c", "sections": [section("s01", "hero"), section("s02", "faq", items=[("Q", "A")])]})
    (ws.work_dir / "thumbnail.png").write_bytes(png_bytes(size=(600, 400)))
    notes = render.export(ws, plan, None, {}, SETTINGS, ["smartstore", "toss"], ["jpg", "webp"])
    out = config.DETAIL_OUTPUT_DIR / ws.code
    assert Image.open(out / "smartstore" / "full.jpg").width == 860
    assert Image.open(out / "toss" / "full.webp").width == 1080
    assert Image.open(out / "toss" / "thumbnail.jpg").size == (1000, 1000)
    assert sorted(p.name for p in (out / "smartstore" / "sections").glob("*.jpg")) == ["01_s01.jpg", "02_s02.jpg"]
    assert len(notes) == 2  # 플랫폼 2개 (빠진 이미지·대표이미지 경고 없음)

    pending = Plan.model_validate({"concept": "c", "sections": [section("s01", "hero", "generate")]})
    notes = render.export(ws, pending, None, {}, SETTINGS, ["smartstore"], ["jpg"])
    assert any("s01" in n and "빈 자리" in n for n in notes)
