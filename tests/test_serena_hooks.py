"""Serena's development hooks: records with sample files, soft delete, replace, restore, approval, an outage, and the
list a mock ETL reads (F12)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fakecspace import bands
from fakecspace.app import store

from .conftest import SERENA


def test_a_record_with_sample_files(client: TestClient) -> None:
    r = client.post("/_fake/media", json={"csid": "m-1", "blob": "b-1"}).json()
    assert r == {"csid": "m-1", "files": ["FullHD", "Medium", "OriginalJpeg", "Small", "Thumbnail", "content"]}
    assert client.get("/cspace-services/media/m-1/blob/content", auth=SERENA).content.startswith(b"\x89PNG")
    xml = client.get("/cspace-services/media/m-1", auth=SERENA).text
    assert "<blobCsid>b-1</blobCsid>" in xml and "<identificationNumber>2026.1.1</identificationNumber>" in xml
    assert "<approvedforweb>true</approvedforweb>" in xml and "'All'</publishTo>" in xml
    assert client.post("/_fake/media", json={"csid": "m-1", "kind": "pdf"}).json()["kept"] is True


@pytest.mark.parametrize(("kind", "type_"), [("pdf", "application/pdf"), ("3D", "model/x3d+xml")])
def test_documents_and_3d(client: TestClient, kind: str, type_: str) -> None:
    client.post("/_fake/media", json={"csid": "m-1", "kind": kind})
    r = client.get("/cspace-services/media/m-1/blob/content", auth=SERENA)
    assert r.headers["content-type"].startswith(type_)
    assert client.get("/cspace-services/media/m-1/blob/derivatives/Thumbnail/content", auth=SERENA).status_code == 404


def test_bad_records_are_refused(client: TestClient) -> None:
    assert client.post("/_fake/media", json={"csid": "m-1", "kind": "audio"}).status_code == 400
    assert client.post("/_fake/media", json={"csid": "m-1", "kind": "pdf", "band": "1MB"}).status_code == 400
    assert client.post("/_fake/media", json={"csid": "m-1", "band": "2MB"}).status_code == 400


def test_soft_delete_and_undelete(client: TestClient) -> None:
    client.post("/_fake/media", json={"csid": "m-1"})
    client.post("/_fake/delete/m-1")
    assert "<workflowState>deleted</workflowState>" in client.get("/cspace-services/media/m-1", auth=SERENA).text
    assert store.media["m-1"]["deleted"] is True
    client.post("/_fake/undelete/m-1")
    assert store.media["m-1"].state == "project"


def test_replace_makes_a_new_blob_and_restore_undoes_it(client: TestClient) -> None:
    client.post("/_fake/media", json={"csid": "m-1", "blob": "b-1"})
    before = client.get("/cspace-services/media/m-1/blob/content", auth=SERENA).content
    new_blob = client.post("/_fake/replace/m-1").json()["blob"]
    assert new_blob != "b-1" and store.media_of_blob(new_blob) is store.media["m-1"]
    assert client.get("/cspace-services/media/m-1/blob/content", auth=SERENA).content != before
    assert client.post("/_fake/restore/m-1").json()["blob"] == "b-1"
    assert client.get("/cspace-services/media/m-1/blob/content", auth=SERENA).content == before


def test_approval_and_removing_the_file(client: TestClient) -> None:
    client.post("/_fake/media", json={"csid": "m-1"})
    client.post("/_fake/approve/m-1", json={"approved": False})
    assert "<approvedforweb>false</approvedforweb>" in client.get("/cspace-services/media/m-1", auth=SERENA).text
    client.post("/_fake/remove-file/m-1")
    assert client.get("/cspace-services/media/m-1/blob/content", auth=SERENA).status_code == 404


def test_a_hook_given_a_blob_csid_says_so(client: TestClient) -> None:
    client.post("/_fake/media", json={"csid": "m-1", "blob": "b-1"})
    r = client.post("/_fake/delete/b-1")
    assert r.status_code == 404 and "Blob of Media record m-1" in r.text


def test_an_outage_answers_503_and_keeps_the_records(client: TestClient) -> None:
    client.post("/_fake/media", json={"csid": "m-1"})
    client.post("/_fake/unreachable", json={"on": True})
    assert client.get("/cspace-services/media/m-1", auth=SERENA).status_code == 503
    client.post("/_fake/unreachable", json={"on": False})
    assert client.get("/cspace-services/media/m-1", auth=SERENA).status_code == 200


def test_the_list_for_a_mock_etl(client: TestClient) -> None:
    client.post("/_fake/media", json={"csid": "m-1", "blob": "b-1"})
    client.post("/_fake/media", json={"csid": "m-2"})
    client.post("/_fake/remove-file/m-2")
    listed = {m["csid"]: m for m in client.get("/_fake/media").json()}
    assert listed["m-1"]["blobCsid"] == "b-1" and listed["m-1"]["files"]
    assert listed["m-2"]["files"] == []


def test_a_band_records_file_is_marked_with_its_csid(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bands, "noise_jpeg", lambda target: b"\xff\xd8" + b"j" * 100)
    bands.reset()
    client.post("/_fake/media", json={"csid": "m-1", "band": "100KB"})
    r = client.get("/cspace-services/media/m-1/blob/content", auth=SERENA)
    assert r.content.startswith(b"\xff\xd8\xff\xfe") and b"fakecspace m-1" in r.content
    assert int(r.headers["content-length"]) == len(r.content)
    bands.reset()


def test_calls_are_recorded_in_order(client: TestClient) -> None:
    client.post("/_fake/media", json={"csid": "m-1"})
    client.get("/cspace-services/media/m-1", auth=SERENA)
    client.get("/cspace-services/media/m-1/blob/content", auth=SERENA)
    assert client.get("/_fake/calls").json() == ["/cspace-services/media/m-1",
                                                 "/cspace-services/media/m-1/blob/content"]
