"""2단계 화면: 사진·카탈로그·사용설명서 → 상세페이지.

① 자료  ② 구성·카피  ③ 이미지  ④ 디자인  ⑤ 내보내기, 오른쪽은 실시간 미리보기.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

from nstore import config
from nstore.config import ConfigError
from nstore.detail import images, planner, render, service
from nstore.detail import theme as theme_mod
from nstore.detail.compliance import LEVEL_ERROR, is_medical
from nstore.detail.claude import ClaudeError, Writer, make_writer
from nstore.detail.gemini import GeminiClient, GeminiError
from nstore.detail.schema import IMAGE_KINDS, IMAGE_MODES, SECTION_LABELS, SECTION_TYPES, Facts, ImageSpec, Item, Plan, Section
from nstore.detail.workspace import Workspace

ERRORS = (ConfigError, ClaudeError, GeminiError, ValueError, FileNotFoundError)
MODE_LABELS = {"photo": "실사진 그대로", "generate": "AI로 만들기", "none": "이미지 없음"}
KIND_LABELS = {"scene": "사용 장면", "detail": "디테일 컷", "cutout": "흰 배경 제품컷", "extend": "실사진 배경 확장"}


# ---------------------------------------------------------------- 공통 도구

@st.cache_resource
def claude() -> Writer:
    """분석·기획·카피·이미지 프롬프트 (터미널의 Claude Code 또는 API — settings.yaml 의 claude.backend)"""
    return make_writer()


@st.cache_resource
def gemini() -> GeminiClient:
    """이미지 그리기"""
    return GeminiClient.from_env()


def flash(message: str, kind: str = "success") -> None:
    st.session_state.setdefault("flash", []).append((kind, message))


def show_flash() -> None:
    for kind, message in st.session_state.pop("flash", []):
        getattr(st, kind)(message)


def run(label: str, func):
    """AI·렌더링 작업 실행. 실패하면 화면에 이유를 보여주고 None."""
    try:
        with st.spinner(label):
            return func()
    except ERRORS as e:
        st.error(str(e))
        return None


def refresh(code: str) -> None:
    """내용이 바뀌었으니 입력칸을 새 값으로 다시 그립니다."""
    for key in [k for k in st.session_state if str(k).startswith(f"{code}:")]:
        del st.session_state[key]
    st.rerun()


@st.cache_data(max_entries=4)
def zip_folder(folder: str, signature: float) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(Path(folder).rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(folder))
    return buf.getvalue()


def section_title(section: Section) -> str:
    first_line = section.headline.replace("\\n", "\n").split("\n")[0] if section.headline else ""
    return f"{section.id} · {SECTION_LABELS.get(section.type, section.type)} · {first_line}"


def replace_section(plan: Plan, new: Section) -> Plan:
    return Plan(concept=plan.concept, sections=[new if s.id == new.id else s for s in plan.sections])


# ---------------------------------------------------------------- 상품 고르기

st.title("상세페이지 만들기")
show_flash()

choices = service.product_choices()
labels = dict(choices)
pick_col, new_col = st.columns([3, 2])
code = pick_col.selectbox(
    "상품", [c for c, _ in choices], format_func=lambda c: labels.get(c, c), index=None,
    placeholder="마스터 시트의 상품을 고르세요",
) if choices else None
typed = new_col.text_input("또는 상품코드 직접 입력", placeholder="예: A1001")
code = typed.strip() or code
if not code:
    st.info("상품을 고르거나 상품코드를 입력하면 시작합니다. 1단계에서 마스터 시트를 만들어 두면 상품명·키워드·의료기기 정보가 자동으로 연결됩니다.")
    st.stop()

ws = Workspace(code)
product = service.product_info(code)
settings = service.settings()
max_gen = settings["gemini"]["max_generated_images"]
plan = ws.load_plan()
facts = ws.load_facts()

with st.sidebar:
    st.caption(f"상품 폴더: {ws.dir}")
    backend = "터미널 Claude Code" if settings["claude"].get("backend", "cli") == "cli" else "Anthropic API"
    st.caption(f"분석·카피·이미지 프롬프트: Claude `{settings['claude']['model']}` ({backend}, effort {settings['claude']['effort']})  \n"
               f"이미지 그리기: Gemini `{settings['gemini']['image_model']}`")
    with st.expander("Gemini 이미지 모델 확인"):
        if st.button("사용 가능한 모델 확인"):
            models = run("확인 중…", lambda: gemini().list_models())
            if models:
                st.code("\n".join(m for m in models if "gemini" in m or "banana" in m))
        st.caption("이름이 다르면 config/settings.yaml 의 gemini 항목을 고치고 화면을 새로고침하세요.")

left, right = st.columns([5, 6], gap="large")

# ---------------------------------------------------------------- 오른쪽: 미리보기

with right:
    st.subheader("미리보기")
    if plan:
        zoom = st.slider("미리보기 크기", 0.4, 1.0, 0.65, 0.05)
        html = render.render_html(plan, ws.load_theme(), ws, product, settings, settings["detail"]["base_width"])
        html = html.replace('<html lang="ko">', f'<html lang="ko" style="zoom:{zoom}">', 1)
        # 카피는 템플릿에서 모두 이스케이프되므로 HTML 안에 AI가 쓴 태그가 그대로 들어가지 않음
        if hasattr(st, "iframe"):
            st.iframe(html, height=1500)
        else:  # 예전 Streamlit
            import streamlit.components.v1 as components

            components.html(html, height=1500, scrolling=True)
    else:
        st.info("② 구성·카피를 만들면 여기에 페이지가 보입니다.")

with left:
    tab_src, tab_plan, tab_img, tab_design, tab_out = st.tabs(["① 자료", "② 구성·카피", "③ 이미지", "④ 디자인", "⑤ 내보내기"])

    # ------------------------------------------------------------ ① 자료
    with tab_src:
        st.caption("여러 각도 사진, 카탈로그, 사용설명서를 올리면 AI가 사실만 뽑아 정리합니다. 카피는 이 정리본에 있는 내용만 씁니다.")
        up_photos = st.file_uploader("제품 사진 (여러 장)", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True, key=f"{code}:up-photos")
        up_docs = st.file_uploader("카탈로그·사용설명서 (PDF 또는 이미지)", type=["pdf", "jpg", "jpeg", "png", "webp"], accept_multiple_files=True, key=f"{code}:up-docs")
        if (up_photos or up_docs) and st.button("올린 파일 저장"):
            for f in up_photos or []:
                ws.add_file(ws.photos_dir, f.name, f.getvalue())
            for f in up_docs or []:
                ws.add_file(ws.docs_dir, f.name, f.getvalue())
            flash(f"사진 {len(up_photos or [])}장, 자료 {len(up_docs or [])}개 저장")
            refresh(code)

        photos = ws.photos()
        if photos:
            st.image([str(p) for p in photos], width=100, caption=[p.name for p in photos])
        st.caption("자료: " + (", ".join(d.name for d in ws.docs()) or "없음"))

        reviews = st.text_area("고객 리뷰 붙여넣기 (선택) — 고객이 좋아한 점·망설인 점을 뽑아 카피와 FAQ에 씁니다",
                               ws.reviews_text(), height=110, key=f"{code}:reviews")
        medical = is_medical(product)
        with st.expander("의료기기 광고 심의 문구", expanded=medical):
            st.caption("의료기기는 상세페이지가 광고 자율심의 대상입니다. 심의 받은 문구를 붙여넣으면 AI가 그 문장만 씁니다. "
                       "의료기기 여부는 마스터 시트의 '의료기기여부' 칸(Y)으로 정합니다." + (" — 이 상품은 의료기기입니다." if medical else ""))
            approved = st.text_area("심의 받은 문구", ws.approved_copy(), height=110, key=f"{code}:approved")
        if st.button("리뷰·심의 문구 저장"):
            if reviews.strip() != ws.reviews_text():
                (ws.work_dir / "reviews.json").unlink(missing_ok=True)  # 리뷰가 바뀌면 다시 분석
            ws.save_text("reviews.txt", reviews)
            ws.save_text("approved_copy.txt", approved)
            flash("저장했습니다.")
            refresh(code)

        st.divider()
        if st.button("자료 정리하기 (AI)", type="primary", disabled=not (photos or ws.docs())):
            msg = run("카탈로그·설명서를 읽는 중…", lambda: service.run_facts(code, claude()))
            if msg:
                flash(msg)
                refresh(code)
        if facts:
            if facts.unknowns:
                st.warning("자료에서 확인 못 한 항목: " + ", ".join(facts.unknowns))
            with st.expander(f"정리된 사실 — 특징 {len(facts.features)}, 규격 {len(facts.specs)} (틀린 곳은 여기서 고치세요)"):
                text = st.text_area("사실 자료 (JSON)", facts.model_dump_json(indent=2), height=420, key=f"{code}:facts")
                if st.button("사실 자료 저장"):
                    try:
                        ws.save_facts(Facts.model_validate_json(text))
                        flash("사실 자료를 저장했습니다.")
                        refresh(code)
                    except ValueError as e:
                        st.error(f"형식이 맞지 않습니다: {e}")

    # ------------------------------------------------------------ ② 구성·카피
    with tab_plan:
        st.caption("후킹 → 공감 → 해결 → 신뢰 → 반박처리 → 행동유도 흐름으로 섹션을 짜고 카피를 씁니다.")
        c1, c2 = st.columns(2)
        if c1.button("구성·카피 만들기 (AI)", type="primary", disabled=facts is None,
                     help=None if facts else "① 자료 정리를 먼저 하세요."):
            msg = run("섹션 구성과 카피를 쓰는 중…", lambda: service.run_plan(code, claude()))
            if msg:
                flash(msg)
                refresh(code)
        versions = len(ws.history())
        if c2.button(f"되돌리기 (기록 {max(versions - 1, 0)}개)", disabled=versions < 2):
            ws.undo()
            flash("바로 전 버전으로 되돌렸습니다.")
            refresh(code)

        if plan:
            st.markdown(f"**컨셉** {plan.concept}")
            findings = service.run_check(code)
            n_err = sum(f.level == LEVEL_ERROR for f in findings)
            if findings:
                with st.expander(f"문구 검사 — 오류 {n_err}개, 주의 {len(findings) - n_err}개", expanded=n_err > 0):
                    for f in findings:
                        (st.error if f.level == LEVEL_ERROR else st.warning)(str(f))
            else:
                st.success("문구 검사 통과")

            page_instr = st.text_input("페이지 전체를 말로 고치기", placeholder="예: 전체 톤을 더 따뜻하게 / FAQ에 배송 질문 추가 / 특징을 3개로 줄여줘",
                                       key=f"{code}:page-instr")
            if st.button("전체 수정 (AI)", disabled=not page_instr):
                updated = run("페이지 전체를 고치는 중…",
                              lambda: planner.edit_page(ws, claude(), plan, page_instr, product, max_gen))
                if updated:
                    flash("페이지 전체를 고쳤습니다. 마음에 안 들면 '되돌리기'를 누르세요.")
                    refresh(code)

            photo_names = [p.name for p in ws.photos()]
            for idx, sec in enumerate(plan.sections):
                k = f"{code}:{sec.id}"
                with st.expander(section_title(sec)):
                    stype = st.selectbox("섹션 종류", SECTION_TYPES, index=SECTION_TYPES.index(sec.type),
                                         format_func=lambda t: SECTION_LABELS[t], key=f"{k}:type")
                    eyebrow = st.text_input("작은 제목", sec.eyebrow, key=f"{k}:eyebrow")
                    headline = st.text_area("헤드라인", sec.headline.replace("\\n", "\n"), height=80, key=f"{k}:headline")
                    body = st.text_area("본문", sec.body.replace("\\n", "\n"), height=90, key=f"{k}:body")
                    items_df = st.data_editor(
                        pd.DataFrame([i.model_dump() for i in sec.items], columns=["title", "text"]),
                        num_rows="dynamic", width="stretch", key=f"{k}:items",
                        column_config={"title": "제목", "text": "내용"},
                    )
                    m1, m2 = st.columns(2)
                    mode = m1.selectbox("이미지", IMAGE_MODES, index=IMAGE_MODES.index(sec.image.mode),
                                        format_func=MODE_LABELS.get, key=f"{k}:mode")
                    photo_opts = [""] + photo_names
                    photo = m2.selectbox("실사진", photo_opts,
                                         index=photo_opts.index(sec.image.photo) if sec.image.photo in photo_opts else 0,
                                         key=f"{k}:photo")
                    kind = sec.image.kind if sec.image.kind in IMAGE_KINDS else "scene"
                    prompt = sec.image.prompt
                    if mode == "generate":
                        kind = st.selectbox("AI 이미지 종류", IMAGE_KINDS, index=IMAGE_KINDS.index(kind),
                                            format_func=KIND_LABELS.get, key=f"{k}:kind")
                        prompt = st.text_input("원하는 장면 (한국어로 쓰면 Claude가 이미지 프롬프트로 바꿉니다)", sec.image.prompt, key=f"{k}:prompt")

                    b1, b2, b3, b4 = st.columns(4)
                    if b1.button("저장", key=f"{k}:save", type="primary"):
                        rows = items_df.fillna("").to_dict("records")
                        new = Section(
                            id=sec.id, type=stype, role=sec.role, eyebrow=eyebrow, headline=headline, body=body,
                            items=[Item(title=str(r["title"]), text=str(r["text"])) for r in rows if str(r["title"]) or str(r["text"])],
                            image=ImageSpec(mode=mode, photo=photo, kind=kind, prompt=prompt),
                        )
                        ws.save_plan(replace_section(plan, new), f"{sec.id} 직접 수정")
                        flash(f"{sec.id} 저장")
                        refresh(code)
                    moved = None
                    if b2.button("위로", key=f"{k}:up", disabled=idx == 0):
                        moved = idx - 1
                    if b3.button("아래로", key=f"{k}:down", disabled=idx == len(plan.sections) - 1):
                        moved = idx + 1
                    if moved is not None:
                        sections = list(plan.sections)
                        sections[idx], sections[moved] = sections[moved], sections[idx]
                        ws.save_plan(Plan(concept=plan.concept, sections=sections), f"{sec.id} 순서 변경")
                        refresh(code)
                    if b4.button("삭제", key=f"{k}:del"):
                        ws.save_plan(Plan(concept=plan.concept, sections=[s for s in plan.sections if s.id != sec.id]), f"{sec.id} 삭제")
                        flash(f"{sec.id} 삭제 — 되돌리기로 복구할 수 있습니다.")
                        refresh(code)

                    instr = st.text_input("이 섹션만 말로 고치기", placeholder="예: 헤드라인을 더 짧게 / 보호자 입장에서 다시",
                                          key=f"{k}:instr")
                    if st.button("AI로 수정", key=f"{k}:ai", disabled=not instr):
                        updated = run("섹션을 고치는 중…", lambda: planner.edit_section(ws, claude(), plan, sec.id, instr, product))
                        if updated:
                            flash(f"{sec.id}를 고쳤습니다.")
                            refresh(code)

    # ------------------------------------------------------------ ③ 이미지
    with tab_img:
        if not plan:
            st.info("② 구성·카피를 먼저 만드세요. 섹션마다 실사진을 쓸지 AI 연출컷을 만들지 계획이 들어갑니다.")
        else:
            planned = [s for s in plan.sections if s.image.mode == "generate"]
            missing = [s for s in planned if not ws.section_image(s.id)]
            st.caption(f"AI 이미지 {len(planned)}장 계획, {len(missing)}장 남음 (상품당 최대 {max_gen}장 — config/settings.yaml). "
                       "Claude가 실사진과 카피를 보고 프롬프트를 쓰고, Gemini가 실사진을 참고해 그립니다. 이미지 안에 글자는 넣지 않습니다.")
            if st.button(f"남은 AI 이미지 {len(missing)}장 만들기", type="primary", disabled=not missing):
                bar = st.progress(0.0)
                msg = run("이미지를 만드는 중…", lambda: service.run_images(code, claude(), gemini(), lambda f, m: bar.progress(f, text=m)))
                if msg:
                    flash(msg)
                    refresh(code)

            for sec in plan.sections:
                if sec.image.mode == "none":
                    continue
                k = f"{code}:{sec.id}"
                with st.container(border=True):
                    kind_label = f" · {KIND_LABELS.get(sec.image.kind, '')}" if sec.image.mode == "generate" else ""
                    st.markdown(f"**{section_title(sec)}**  \n{MODE_LABELS[sec.image.mode]}{kind_label}")
                    current = ws.section_image(sec.id) if sec.image.mode == "generate" else ws.photo(sec.image.photo)
                    if current:
                        st.image(str(current), width=280)
                    if sec.image.mode == "generate" and ws.image_prompt(sec.id):
                        with st.expander("Gemini에 보낸 프롬프트"):
                            st.write(ws.image_prompt(sec.id))
                    if sec.image.mode != "generate":
                        continue
                    img_instr = st.text_input("이미지를 말로 고치기", placeholder="예: 배경을 거실로 / 할머니가 웃는 모습으로",
                                              key=f"{k}:img-instr")
                    c1, c2, c3 = st.columns(3)
                    if c1.button("새로 만들기", key=f"{k}:regen"):
                        if run("이미지를 만드는 중…", lambda: images.generate_section_image(ws, claude(), gemini(), sec, settings)):
                            refresh(code)
                    if c2.button("말한 대로 고치기", key=f"{k}:img-edit", disabled=not img_instr):
                        if run("이미지를 고치는 중…", lambda: images.edit_section_image(ws, claude(), gemini(), sec, img_instr, settings)):
                            refresh(code)
                    if c3.button("이전 이미지로", key=f"{k}:img-undo", disabled=not ws.has_image_history(sec.id)):
                        ws.undo_section_image(sec.id)
                        refresh(code)

        st.divider()
        st.markdown("**대표이미지 (썸네일)**")
        st.caption("네이버 쇼핑 대표이미지는 흰 배경에 글자·로고 없이 올리는 것이 권장되어, 흰 배경 제품컷으로 만듭니다.")
        thumb = ws.work_dir / "thumbnail.png"
        if st.button("대표이미지 만들기", disabled=not ws.photos()):
            msg = run("대표이미지를 만드는 중…", lambda: service.run_thumbnail(code, claude(), gemini()))
            if msg:
                refresh(code)
        if thumb.exists():
            st.image(str(thumb), width=280)
            if (ws.work_dir / "thumbnail.txt").exists():
                with st.expander("Gemini에 보낸 프롬프트"):
                    st.write((ws.work_dir / "thumbnail.txt").read_text(encoding="utf-8"))

    # ------------------------------------------------------------ ④ 디자인
    with tab_design:
        current = ws.load_theme() or theme_mod.DEFAULT_THEME
        scope = st.radio("적용 범위", ["모든 상품", "이 상품만"], horizontal=True, key=f"{code}:scope")
        target = config.THEME_PATH if scope == "모든 상품" else ws.dir / "theme.json"

        st.markdown("**브랜드 메인 색 하나로 전체 색 맞추기**")
        c1, c2, c3 = st.columns(3)
        color = c1.color_picker("메인 색", current.primary, key=f"{code}:color")
        fonts = list(theme_mod.FONTS)
        font = c2.selectbox("제목 글꼴", fonts, index=fonts.index(current.font), format_func=theme_mod.FONTS.get, key=f"{code}:font")
        radius = c3.slider("모서리 둥글기", 0, 40, current.radius, key=f"{code}:radius")
        if st.button("이 색으로 적용", type="primary"):
            ws.ensure()
            theme_mod.save(theme_mod.from_brand_color(color, font, radius), target)
            flash(f"디자인을 적용했습니다 ({scope}).")
            refresh(code)

        st.markdown("**마음에 드는 상세페이지 분위기 가져오기**")
        refs = st.file_uploader("레퍼런스 페이지 캡처 (1~3장)", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True, key=f"{code}:refs")
        if refs and st.button("레퍼런스 반영 (AI)"):
            saved = [ws.add_file(ws.work_dir / "refs", f.name, f.getvalue()) for f in refs[:3]]
            theme = run("레퍼런스를 분석하는 중…", lambda: theme_mod.from_reference(claude(), saved))
            if theme:
                theme_mod.save(theme, target)
                flash(f"레퍼런스 분위기를 반영했습니다: {theme.mood}")
                refresh(code)

        swatches = "".join(
            f'<div style="text-align:center;font-size:12px"><div style="width:56px;height:56px;border-radius:12px;'
            f'background:{getattr(current, k)};border:1px solid #ddd"></div>{label}</div>'
            for k, label in (("primary", "메인"), ("accent", "보조"), ("surface", "배경면"), ("text", "글자"), ("muted", "보조글자"))
        )
        st.markdown(f'<div style="display:flex;gap:12px;margin-top:8px">{swatches}</div>', unsafe_allow_html=True)
        st.caption(f"현재: {current.mood} · 글꼴 {theme_mod.FONTS[current.font]} · 모서리 {current.radius}px")

    # ------------------------------------------------------------ ⑤ 내보내기
    with tab_out:
        platforms = settings["detail"]["platforms"]
        chosen = st.multiselect("플랫폼 규격", list(platforms), default=list(platforms),
                                format_func=lambda p: f"{platforms[p]['label']} {platforms[p]['width']}px", key=f"{code}:platforms")
        formats = st.multiselect("파일 형식", settings["detail"]["formats"], default=["jpg"], key=f"{code}:formats")
        st.caption("섹션별 이미지(스마트에디터에 차례로 올리기 좋음)와 전체를 이은 긴 이미지 한 장, 대표이미지를 만듭니다.")
        if plan and any(f.level == LEVEL_ERROR for f in service.run_check(code)):
            st.warning("② 문구 검사에 오류가 있습니다. 게시 전에 꼭 고치세요.")
        if st.button("이미지로 내보내기", type="primary", disabled=not (plan and chosen and formats)):
            notes = run("플랫폼별로 찍는 중…", lambda: service.run_export(code, chosen, formats))
            for note in notes or []:
                flash(note, "info")
            if notes:
                refresh(code)

        out_dir = config.DETAIL_OUTPUT_DIR / ws.code
        if out_dir.exists():
            files = [p for p in out_dir.rglob("*") if p.is_file()]
            if files:
                st.caption(f"저장 위치: {out_dir}")
                signature = max(p.stat().st_mtime for p in files)
                st.download_button("전체 받기 (zip)", zip_folder(str(out_dir), signature), file_name=f"{ws.code}_상세페이지.zip")
