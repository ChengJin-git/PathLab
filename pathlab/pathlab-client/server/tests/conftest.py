import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from unittest.mock import MagicMock

from helpers import _make_user

load_dotenv(Path(__file__).parents[2] / ".env")

@pytest.fixture
def admin_user() -> MagicMock:
    return _make_user("admin")


@pytest.fixture
def guest_user() -> MagicMock:
    return _make_user("guest")
