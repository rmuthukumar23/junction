from pathlib import Path

import pytest

from envkit.scenario import load_scenario

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def scenario():
    return load_scenario(ROOT / "tests" / "envkit" / "fixtures" / "depot-basic.toml")
