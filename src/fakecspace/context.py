"""Which museum a request is for, and its store."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import Request

from .store import DEFAULT_MUSEUM, TENANT_IDS, Store, Stores

stores = Stores()
store = stores[DEFAULT_MUSEUM]  # PAHMA's: what a request gets when it names no museum


def museum_of_scope(scope: Mapping[str, Any]) -> str:
    """The museum a request is for: the path prefix it came with (MuseumPrefix), or else the first label of the host
    name; PAHMA when neither names one."""
    prefixed = scope.get("fake_museum")
    if prefixed:
        return str(prefixed)
    host = next((v.decode("latin-1") for k, v in scope.get("headers", []) if k == b"host"), "")
    label = host.split(":")[0].split(".")[0].lower()
    return label if label in TENANT_IDS else DEFAULT_MUSEUM


def museum_of(request: Request) -> str:
    return museum_of_scope(request.scope)


def store_of(request: Request) -> Store:
    return stores[museum_of(request)]
