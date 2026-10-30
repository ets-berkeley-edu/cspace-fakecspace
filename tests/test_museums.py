"""One store per museum (F8), told apart by host name or path prefix; reset empties them all; seeds (F9)."""
from __future__ import annotations

from fastapi import Request
from fastapi.testclient import TestClient

from fakecspace.app import app, museum_of, store, stores
from fakecspace.store import TENANT_IDS

from .conftest import ADMIN, SERENA, museum


def test_a_record_is_seen_only_through_its_own_museum() -> None:
    museum("ucjeps").post("/_fake/media", json={"csid": "m-1"})
    assert museum("ucjeps").get("/cspace-services/media/m-1", auth=SERENA).status_code == 200
    assert museum("pahma").get("/cspace-services/media/m-1", auth=SERENA).status_code == 404
    assert "m-1" in stores["ucjeps"].media and "m-1" not in store.media


def test_the_path_prefix_names_the_museum_and_is_removed() -> None:
    client = TestClient(app, base_url="http://fakecspace.serena")
    client.post("/bampfa/_fake/media", json={"csid": "m-1"})
    assert client.get("/bampfa/cspace-services/media/m-1", auth=SERENA).status_code == 200
    assert client.get("/pahma/cspace-services/media/m-1", auth=SERENA).status_code == 404
    assert stores["bampfa"].calls == ["/cspace-services/media/m-1"]


def test_a_host_that_names_no_museum_is_pahma(client: TestClient) -> None:
    client.post("/_fake/media", json={"csid": "m-1"})
    assert "m-1" in stores["pahma"].media


def test_museum_of_reads_the_host_or_the_prefix(client: TestClient) -> None:
    @app.get("/_fake/test-museum")
    def which(request: Request) -> str:
        return museum_of(request)

    assert museum("botgarden").get("/_fake/test-museum").json() == "botgarden"
    assert client.get("/cinefiles/_fake/test-museum").json() == "cinefiles"
    assert client.get("/_fake/test-museum").json() == "pahma"
    app.router.routes.pop()


def test_reset_empties_every_museum(client: TestClient) -> None:
    for name in TENANT_IDS:
        museum(name).post("/_fake/media", json={"csid": f"m-{name}"})
        museum(name).post("/_fake/unreachable", json={"on": True})
    assert client.post("/_fake/reset").json() == {"ok": True}
    assert all(not s.media and not s.unreachable for s in stores.values())


def test_the_bmu_samples_are_seeded_on_request_and_once(client: TestClient) -> None:
    assert not store.objects and not store.media  # empty until a client seeds
    assert client.post("/_fake/seed", json={"set": "bmu"}).json() == {"museum": "pahma", "seeded": ["bmu"]}
    client.post("/_fake/seed", json={"set": "bmu"})
    assert len(store.objects) == 14 and len(store.media) == 1
    numbers = [o["objectNumber"] for o in client.get("/_fake/objects").json()]
    assert numbers.count("9-9999") == 2 and "3-1004" in numbers
    assert not stores["ucjeps"].objects


def test_an_unknown_sample_set_is_refused(client: TestClient) -> None:
    r = client.post("/_fake/seed", json={"set": "nope"})
    assert r.status_code == 400 and "bmu" in r.text
    assert client.post("/_fake/seed", json={"set": "bmu", "extra": 1}).status_code == 422


def test_settings_say_which_museum(client: TestClient) -> None:
    assert museum("cinefiles").get("/_fake/settings").json()["museum"] == "cinefiles"
    assert client.get("/_fake/state", auth=ADMIN).json()["museum"] == "pahma"
