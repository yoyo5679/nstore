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

    args = parser.parse_args(argv)
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


if __name__ == "__main__":
    sys.exit(main())
