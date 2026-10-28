import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nstore import config  # noqa: E402


@pytest.fixture
def settings():
    return config.load_yaml("settings.yaml")


@pytest.fixture
def rules():
    return config.load_yaml("title_rules.yaml")
