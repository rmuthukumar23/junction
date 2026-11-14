from pathlib import Path

import pytest

from envkit.scenario import load_scenario

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def scenario():
    return load_scenario(ROOT / "scenarios" / "depot-basic.toml")
