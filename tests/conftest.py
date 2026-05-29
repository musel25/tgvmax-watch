import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sncf_search_response() -> dict:
    return json.loads((FIXTURES / "sncf_connect_search.json").read_text())
