#!/bin/bash
# 프로그램 실행 — Finder에서 더블클릭하거나, 터미널에서:  bash 2_start.command
# 브라우저에 화면이 열립니다. 끝낼 때는 이 터미널 창에서 Control + C.
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "아직 설치가 안 됐습니다. 1_setup.command 를 먼저 실행하세요."
  exit 1
fi
source .venv/bin/activate
streamlit run app.py
