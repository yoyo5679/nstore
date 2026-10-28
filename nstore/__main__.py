"""명령줄 실행: python -m nstore <명령>"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import pipeline
from .config import ConfigError
from .naver import NaverAPIError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m nstore", description="자사몰 → 스마트스토어 상품 등록 도구")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("import", help="아임웹 엑셀 → data/master.xlsx")
    p.add_argument("file", type=Path)
    p.add_argument("--force", action="store_true", help="기존 master.xlsx 덮어쓰기")

    p = sub.add_parser("keywords", help="품목별 키워드 조사 → data/keywords.xlsx")
    p.add_argument("items", nargs="*", help="조사할 품목 (생략하면 마스터 시트에 있는 품목 전체)")

    sub.add_parser("titles", help="추천 상품명·태그 생성 → data/master.xlsx")

    p = sub.add_parser("export", help="스마트스토어 일괄등록 엑셀 → output/smartstore_upload.xlsx")
    p.add_argument("--template", type=Path, help="스마트스토어센터에서 받은 일괄등록 양식")

    p = sub.add_parser("detail", help="상세페이지: products/<상품코드>/ 의 사진·자료로 만들기")
    p.add_argument("step", choices=DETAIL_STEPS, help="links→facts→plan→images→thumbnail→export, all=전부, check=문구 검사, models=Gemini 이미지 모델 목록")
    p.add_argument("codes", nargs="*", help="상품코드 (여러 개 가능)")
    p.add_argument("--all", action="store_true", help="products/ 에 사진·자료가 있는 상품 전체")
    p.add_argument("--platform", nargs="+", choices=["smartstore", "coupang", "toss"], help="내보낼 플랫폼 (기본: 전부)")
    p.add_argument("--format", nargs="+", choices=["jpg", "png", "webp"], default=["jpg"], help="이미지 형식 (기본: jpg)")
    p.add_argument("--redo", action="store_true", help="all 단계에서 이미 끝난 자료 정리·구성·대표이미지도 다시 만들기")

    args = parser.parse_args(argv)
    if args.command == "detail":
        return run_detail(args)
    try:
        if args.command == "import":
            notes = pipeline.run_import(args.file, args.force)
        elif args.command == "keywords":
            notes = pipeline.run_keywords(args.items, progress=lambda _, msg: print(msg, flush=True))
        elif args.command == "titles":
            notes = pipeline.run_titles()
        else:
            notes = pipeline.run_export(args.template)
    except (ConfigError, NaverAPIError, FileExistsError, FileNotFoundError, ValueError) as e:
        print(f"[중단] {e}", file=sys.stderr)
        return 1
    print("\n".join(notes))
    return 0


DETAIL_STEPS = ["links", "facts", "plan", "images", "thumbnail", "export", "all", "check", "models"]


def run_detail(args) -> int:
    """여러 상품을 차례로 처리합니다. 한 상품이 실패해도 나머지는 계속합니다.

    'all' 은 이미 끝난 단계를 건너뛰므로, 중간에 멈춰도 같은 명령을 다시 실행하면 이어서 합니다.
    Claude 사용 한도에 걸리면 거기서 멈춥니다.
    """
    from .detail import service
    from .detail.capture import CaptureError
    from .detail.claude import ClaudeError, ClaudeLimitError, make_writer
    from .detail.gemini import GeminiClient, GeminiError
    from .detail.workspace import Workspace

    # Claude: 분석·기획·카피·이미지 프롬프트 / Gemini: 이미지 그리기
    try:
        writer = make_writer() if args.step in ("facts", "plan", "images", "thumbnail", "all") else None
        painter = GeminiClient.from_env() if args.step in ("images", "thumbnail", "all", "models") else None
        if args.step == "models":
            print("\n".join(painter.list_models()))
            return 0
    except (ConfigError, GeminiError, ClaudeError) as e:
        print(f"[중단] {e}", file=sys.stderr)
        return 1

    codes = args.codes or (service.codes_with_material() if args.all else [])
    if not codes:
        print("[중단] 상품코드를 적거나 --all 을 붙이세요.", file=sys.stderr)
        return 1

    steps = ["links", "facts", "plan", "images", "thumbnail", "export"] if args.step == "all" else [args.step]
    resume = args.step == "all" and not args.redo
    failed = []
    for n, code in enumerate(codes):
        ws = Workspace(code)
        done = {"links": bool(ws.captured_links()) or not ws.links_path().exists(),
                "facts": ws.load_facts() is not None, "plan": ws.load_plan() is not None,
                "thumbnail": (ws.work_dir / "thumbnail.png").exists()}
        try:
            for step in steps:
                if resume and done.get(step):
                    continue
                if step == "links":
                    for note in service.run_links(code):
                        print(code, note, flush=True)
                elif step == "facts":
                    print(code, service.run_facts(code, writer), flush=True)
                elif step == "plan":
                    print(code, service.run_plan(code, writer), flush=True)
                elif step == "images":
                    print(code, service.run_images(code, writer, painter), flush=True)
                elif step == "thumbnail":
                    print(code, service.run_thumbnail(code, writer, painter), flush=True)
                elif step == "export":
                    for note in service.run_export(code, args.platform, args.format):
                        print(code, note, flush=True)
                elif step == "check":
                    findings = service.run_check(code)
                    print(code, "문구 검사 통과" if not findings else "")
                    for f in findings:
                        print("   ", f)
        except ClaudeLimitError as e:
            print(f"{code} [멈춤] {e}", file=sys.stderr, flush=True)
            print(f"남은 상품 {len(codes) - n}개 — 한도가 풀리면 같은 명령을 다시 실행하세요.", file=sys.stderr)
            return 1
        except (ConfigError, ClaudeError, GeminiError, CaptureError, ValueError, FileNotFoundError) as e:
            failed.append(code)
            print(f"{code} [실패] {e}", file=sys.stderr, flush=True)
    if failed:
        print(f"실패 {len(failed)}개: {', '.join(failed)}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
