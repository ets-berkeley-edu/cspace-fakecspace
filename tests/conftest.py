from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from fakecspace.app import app, stores

ADMIN = ("admin", "admin")
SERENA = ("serena", "serena")


@pytest.fixture(autouse=True)
def empty() -> Iterator[None]:
    stores.reset()
    yield
    stores.reset()


@pytest.fixture
def client() -> TestClient:
    """PAHMA's CollectionSpace (a host name that names no museum)."""
    return TestClient(app, base_url="http://fake")


def museum(name: str) -> TestClient:
    """One museum's CollectionSpace, by host name."""
    return TestClient(app, base_url=f"http://{name}.fakecspace:8180")
