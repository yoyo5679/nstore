#!/bin/bash
# 맥 처음 설치 — Finder에서 더블클릭하거나, 터미널에서:  bash 1_setup.command
set -e
cd "$(dirname "$0")"

echo "== 스마트스토어 상품 등록 도구 설치 =="

# 파이썬 3.10 이상 찾기 (맥 기본 python3 는 3.9라서 안 됨)
PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    PY="$cand"
    break
  fi
done
if [ -z "$PY" ]; then
  if ! command -v brew >/dev/null 2>&1; then
    echo "파이썬 3.10 이상과 Homebrew가 없습니다. https://brew.sh 의 설치 명령을 터미널에 붙여넣어 Homebrew를 먼저 설치한 뒤 다시 실행하세요."
    exit 1
  fi
  brew install python@3.12
  PY=python3.12
fi
echo "파이썬: $("$PY" --version)"

[ -d .venv ] || "$PY" -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium

if [ ! -f .env ]; then
  cp .env.example .env
  echo ".env 파일을 만들었습니다. 열리는 편집기에서 키를 채우고 저장하세요."
  open -e .env || true
fi

if ! command -v claude >/dev/null 2>&1; then
  echo
  echo "Claude Code가 없습니다. 상세페이지 글 작성에 필요합니다. 터미널에 아래 명령을 붙여넣어 설치한 뒤 'claude' 를 실행해 로그인하세요."
  echo "  curl -fsSL https://claude.ai/install.sh | bash"
fi

echo
echo "설치 끝! 이제 2_start.command 를 더블클릭하면 프로그램이 열립니다."
