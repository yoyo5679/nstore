"""설정 파일(config/*.yaml)과 API 키(.env) 읽기."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"

MASTER_PATH = DATA_DIR / "master.xlsx"
KEYWORDS_PATH = DATA_DIR / "keywords.xlsx"
CACHE_PATH = DATA_DIR / "cache.sqlite"
SMARTSTORE_OUTPUT_PATH = OUTPUT_DIR / "smartstore_upload.xlsx"
PRODUCTS_DIR = ROOT / "products"
DETAIL_OUTPUT_DIR = OUTPUT_DIR / "detail"
THEME_PATH = DATA_DIR / "theme.json"

load_dotenv(ROOT / ".env")


class ConfigError(RuntimeError):
    pass


def load_yaml(name: str) -> dict:
    path = CONFIG_DIR / name
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} 값이 .env 에 없습니다. .env.example 을 참고해 채워주세요.")
    return value
