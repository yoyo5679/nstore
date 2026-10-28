"""자료 정리 → 리뷰 분석 → 섹션 구성·카피 → 말로 수정. 모두 Claude가 합니다."""

from __future__ import annotations

import json

from .compliance import is_medical
from .claude import Writer
from .schema import IMAGE_KINDS, IMAGE_MODES, SECTION_LABELS, SECTION_TYPES, Facts, Plan, ReviewInsights, Section
from .workspace import Workspace

SYSTEM = """당신은 한국 복지용구·실버용품 전문 상세페이지 기획자이자 카피라이터입니다.
구매를 결정하는 사람은 주로 부모님을 돌보는 40~60대 자녀(보호자)이고, 실제 사용자는 어르신입니다.

반드시 지킬 원칙:
1. 사실 자료(facts)에 있는 내용만 씁니다. 숫자·규격·인증 번호는 자료 표기 그대로 쓰고, 자료에 없는 숫자는 만들지 않습니다.
2. 효능·효과를 과장하지 않습니다. '치료', '완치', '예방 보장', '최고', '1위', '유일', '부작용 없음' 같은 표현은 쓰지 않습니다.
3. 장기요양 본인부담금 할인·면제·무료를 암시하는 문구를 쓰지 않습니다.
4. 문장은 짧고 쉽게, 존댓말로 씁니다. 헤드라인은 두 줄 이내로 짧게 쓰고, 줄을 나눌 곳에는 \\n 을 넣습니다.
5. 모든 글은 한국어로 씁니다."""

FLOW = """기본 흐름 (상품에 맞게 섹션을 빼거나 feature 를 2~4개로 조절할 수 있습니다):
- hero (후킹): 보호자가 멈춰서 읽게 만드는 첫 화면. eyebrow 에 브랜드나 품목, headline 에 핵심 약속.
- problem (공감): 보호자·어르신이 겪는 구체적인 불편 3가지. items 에 (title=불편, text=상황 설명).
- solution (해결): 이 제품이 그 불편을 어떻게 덜어주는지 한 문장 + 제품 소개.
- feature × 2~4 (해결): 특징 하나당 섹션 하나. eyebrow 는 비워두면 'POINT 01'처럼 자동으로 붙습니다.
- trust (신뢰): 허가·인증·제조사 등 자료에 있는 것만. items 에 (title=항목, text=내용). 자료에 없으면 섹션을 빼세요.
- usage (정보): 사용 순서. items 에 (title='STEP 1' 형식, text=설명).
- faq (반박처리): 구매 전 망설이는 질문과 답. 리뷰의 불만·질문이 있으면 그것을 우선. items 에 (title=질문, text=답).
- spec (정보): 규격·구성품. items 에 (title=항목명, text=값). 자료의 specs·components 를 그대로.
- caution (정보): 사용 시 주의사항. items 에 (title='', text=주의 문장).
- cta (행동유도): 마무리 메시지와 문의·구매 안내. 할인·무료 표현 금지."""

IMAGE_RULES = """이미지 계획 (image):
- mode='photo': 실사진을 그대로 씁니다. photo 에 아래 실사진 목록의 파일명을 정확히 적습니다.
- mode='generate': AI가 실사진을 참고해 새 이미지를 만듭니다. kind 는
  scene(사용 장면, 한국 가정에서 어르신·보호자가 쓰는 모습), detail(부분 확대), cutout(흰 배경 제품컷),
  extend(실사진 배경을 넓혀 화면을 채움 — photo 에 원본 파일명) 중 하나. prompt 에 원하는 장면을 한국어로 구체적으로 적습니다
  (누가, 어디서, 제품의 어느 부분을, 어떤 분위기로). 실제 이미지 생성 지시문은 나중에 따로 만듭니다.
  generate 일 때 photo 에는 제품 모양을 맞출 기준 사진을 적어도 됩니다.
- mode='none': 이미지 없음 (faq, caution, spec 등 글이 중심인 섹션).
- AI 생성 이미지는 최대 {max_generate}장까지만 계획하세요. 나머지는 실사진이나 none 으로."""


def _dump(obj) -> str:
    return obj.model_dump_json(indent=1) if obj is not None else "없음"


def extract_facts(ws: Workspace, client: Writer, product: dict) -> Facts:
    files = ws.docs() + ws.photos()[:6]
    if not files:
        raise ValueError(f"{ws.dir} 에 사진(photos/)이나 자료(docs/)가 없습니다.")
    prompt = f"""첨부한 카탈로그·사용설명서·제품 사진·제품 설명 링크 캡처만 근거로 이 제품의 사실을 정리하세요.

- 자료에 없는 내용은 절대 만들지 마세요. 확인하지 못한 중요한 정보(무게, 최대 하중, 재질 등)는 unknowns 에 적으세요.
- 각 목록에는 자료에 실제로 적힌 항목만 넣으세요. 해당 내용이 없으면 빈 목록으로 두세요.
  "자료에 없습니다" 같은 설명이나 메모는 목록에 넣지 말고 unknowns 에만 적으세요. 이 목록들은 상세페이지에 그대로 실립니다.
- 숫자는 자료에 적힌 그대로 단위까지 적으세요. specs[].value 에는 값만 적고 출처는 붙이지 마세요.
- components 에는 자료에 적힌 구성품만 적으세요. 사진으로 본 외형을 추측해 적지 마세요.
- features[].source 에만 근거(파일 이름과 페이지)를 적으세요.
- certifications 에는 의료기기 허가·신고 번호, 인증, 복지용구 제품코드 등 자료에 적힌 것만 적으세요.
- 효능·효과는 자료의 표현을 바꾸거나 부풀리지 마세요.
- link-로 시작하는 파일은 제품 설명 웹페이지를 캡처한 것입니다(글자는 .txt, 화면은 .png 조각). 광고 문구보다
  규격·구성·사용법·주의사항 같은 사실을 뽑고, 메뉴·배송·쿠폰·다른 상품 같은 페이지 주변 내용은 무시하세요.

참고 정보: {json.dumps(product, ensure_ascii=False)}"""
    facts = client.json(prompt, Facts, files=files, system=SYSTEM)
    ws.save_facts(facts)
    return facts


def analyze_reviews(ws: Workspace, client: Writer) -> ReviewInsights | None:
    text = ws.reviews_text()
    if not text:
        return None
    prompt = f"""아래는 이 제품(또는 같은 종류 제품)의 고객 리뷰입니다.
상세페이지에 쓸 수 있도록 정리하세요.
- selling_points: 고객이 실제로 좋다고 한 점 (리뷰 표현을 살려서)
- complaints: 불만·아쉬운 점
- questions: 구매 전에 망설였거나 궁금해한 점
과장하거나 리뷰에 없는 내용을 만들지 마세요.

리뷰:
{text[:30000]}"""
    insights = client.json(prompt, ReviewInsights, system=SYSTEM)
    ws.save_reviews(insights)
    return insights


def _medical_rule(product: dict, approved: str) -> str:
    if not is_medical(product):
        return ""
    if approved:
        return f"""
[의료기기 — 광고 자율심의 문구만 사용]
이 제품은 의료기기라 상세페이지가 광고 심의 대상입니다. headline·body·items 의 문장은 아래 심의 받은 문구에 있는 문장만 그대로 쓰세요.
새 문장을 만들거나 바꿔 쓰지 마세요. 맞는 문구가 없는 칸은 비워두세요.
심의 문구:
{approved}"""
    return """
[의료기기 — 심의 전 초안]
이 제품은 의료기기라 상세페이지를 게시하기 전에 광고 자율심의를 받아야 합니다. 심의 신청용 초안으로, 자료 문장을 최대한 그대로 옮기고 해석·평가하는 표현을 넣지 마세요."""


def _reference_rule(ws: Workspace) -> str:
    guide = ws.load_reference()
    if guide is None:
        return ""
    flow = " → ".join(guide.section_flow) or "기본 흐름"
    notes = "; ".join(guide.notes)
    return f"""
[레퍼런스 스타일을 따라 하세요]
- 섹션 흐름: {flow} (우리 자료에 없는 내용의 섹션은 빼세요)
- 말투: {guide.copy_tone}
- 사진 분위기: {guide.photo_style} (image.prompt 의 장면에 반영)
- 그 밖에: {notes}
레퍼런스는 스타일만 따릅니다. 레퍼런스의 문장·표현·주장을 그대로 가져오지 말고, 우리 사실 자료로 새로 쓰세요."""


def make_plan(ws: Workspace, client: Writer, product: dict, keywords: dict, max_generate: int) -> Plan:
    facts = ws.load_facts()
    if facts is None:
        raise ValueError("먼저 자료 정리(사실 추출)를 하세요.")
    reviews = ws.load_reviews() or analyze_reviews(ws, client)
    photos = [p.name for p in ws.photos()]

    prompt = f"""이 제품의 상세페이지 섹션 구성과 카피, 이미지 계획을 만드세요.

{FLOW}

{IMAGE_RULES.format(max_generate=max_generate)}

검색 키워드: 메인 '{keywords.get("main", "")}', 관련 {keywords.get("tags", [])}
→ hero 나 solution 의 본문에 메인 키워드를 자연스럽게 한 번 넣으세요. 억지로 반복하지 마세요.

상품 정보: {json.dumps(product, ensure_ascii=False)}
실사진 목록: {photos}
사실 자료(facts): {_dump(facts)}
리뷰 분석: {_dump(reviews)}
{_medical_rule(product, ws.approved_copy())}
{_reference_rule(ws)}

concept 에는 이 페이지의 핵심 메시지를 한 문장으로 적으세요.
각 섹션의 id 는 s01, s02 … 순서대로 붙이세요."""
    plan = client.json(prompt, Plan, files=ws.photos()[:6], system=SYSTEM)
    plan = normalize_plan(plan, photos, max_generate)
    ws.save_plan(plan, "AI 구성·카피 생성")
    return plan


def edit_section(ws: Workspace, client: Writer, plan: Plan, section_id: str, instruction: str, product: dict) -> Plan:
    """한 섹션만 말로 고칩니다."""
    target = next(s for s in plan.sections if s.id == section_id)
    prompt = f"""상세페이지의 섹션 하나만 고치세요.

요청: {instruction}

- id('{target.id}')와 type('{target.type}')은 바꾸지 마세요.
- 요청과 관계없는 부분(이미지 계획 등)은 그대로 두세요.
- 원칙(사실 자료에 있는 내용만, 과장 금지)을 지키세요.

고칠 섹션: {target.model_dump_json(indent=1)}
페이지 컨셉: {plan.concept}
사실 자료: {_dump(ws.load_facts())}
{_medical_rule(product, ws.approved_copy())}"""
    new = client.json(prompt, Section, system=SYSTEM)
    new.id, new.type = target.id, target.type
    sections = [new if s.id == section_id else s for s in plan.sections]
    updated = normalize_plan(Plan(concept=plan.concept, sections=sections), [p.name for p in ws.photos()], 99)
    ws.save_plan(updated, f"{SECTION_LABELS.get(target.type, target.type)} 수정: {instruction[:40]}")
    return updated


def edit_page(ws: Workspace, client: Writer, plan: Plan, instruction: str, product: dict, max_generate: int) -> Plan:
    """페이지 전체(톤, 순서, 섹션 추가·삭제)를 말로 고칩니다."""
    prompt = f"""상세페이지 전체에 다음 요청을 반영하세요.

요청: {instruction}

- 기존 섹션의 id 는 유지하고, 새로 넣는 섹션은 겹치지 않는 새 id 를 쓰세요.
- 요청과 관계없는 섹션·이미지 계획은 그대로 두세요.
- 원칙(사실 자료에 있는 내용만, 과장 금지)을 지키세요.

{IMAGE_RULES.format(max_generate=max_generate)}

현재 페이지: {plan.model_dump_json(indent=1)}
사실 자료: {_dump(ws.load_facts())}
실사진 목록: {[p.name for p in ws.photos()]}
{_medical_rule(product, ws.approved_copy())}
{_reference_rule(ws)}"""
    updated = normalize_plan(client.json(prompt, Plan, system=SYSTEM), [p.name for p in ws.photos()], max_generate)
    ws.save_plan(updated, f"전체 수정: {instruction[:40]}")
    return updated


def normalize_plan(plan: Plan, photos: list[str], max_generate: int) -> Plan:
    """AI 응답을 안전한 형태로 다듬습니다: 중복·빈 id, 없는 사진, 생성 이미지 수 제한."""
    seen: set[str] = set()
    generated = 0
    for n, section in enumerate(plan.sections, start=1):
        if not section.id or section.id in seen:
            section.id = next(f"s{k:02d}" for k in range(n, 1000) if f"s{k:02d}" not in seen)
        seen.add(section.id)
        if section.type not in SECTION_TYPES:
            section.type = "solution"

        image = section.image
        if image.mode not in IMAGE_MODES:
            image.mode = "none"
        if image.mode == "photo" and image.photo not in photos:
            image.photo = photos[0] if photos else ""
            image.mode = "photo" if photos else "none"
        if image.mode == "generate":
            if image.kind not in IMAGE_KINDS:
                image.kind = "scene"
            if image.kind == "extend" and image.photo not in photos:
                image.photo = photos[0] if photos else ""
            generated += 1
            if generated > max_generate:
                image.mode, image.photo = ("photo", photos[0]) if photos else ("none", "")
    return plan
