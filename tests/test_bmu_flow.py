"""What the BMU does: create a Media record, attach a file, make an Object, relate them, make a group; and what Serena
then gets for a file uploaded that way (F10, F11)."""
from __future__ import annotations

import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fakecspace.app import KEEP_BYTES, store
from fakecspace.store import DERIVATIVES

from .conftest import ADMIN, SERENA, museum

MEDIA_XML = (b'<document name="media"><ns2:media_common xmlns:ns2="http://collectionspace.org/services/media">'
             b"<identificationNumber>20-0501</identificationNumber><title>20-0501_a.jpg</title></ns2:media_common>"
             b'<ns2:media_pahma xmlns:ns2="http://collectionspace.org/services/media/local/pahma">'
             b"<approvedForWeb>false</approvedForWeb></ns2:media_pahma></document>")


def created(r: Any) -> str:
    assert r.status_code == 201, r.text
    return str(r.headers["location"]).rsplit("/", 1)[1]


def upload(client: TestClient, csid: str, data: bytes, name: str = "20-0501_a.jpg") -> str:
    return created(client.put(f"/cspace-services/media/{csid}/blob", auth=ADMIN,
                              files={"file": (name, data, "image/jpeg")}))


def test_a_media_record_and_its_file(client: TestClient) -> None:
    csid = created(client.post("/cspace-services/media", auth=ADMIN, content=MEDIA_XML))
    media = store.media[csid]
    assert media["identificationNumber"] == "20-0501" and media["blobCsid"] == "" and "xml" in media
    assert media.approved_for_web is False
    blob = upload(client, csid, b"jpeg bytes")
    assert media["blobCsid"] == blob and store.blobs[blob]["media"] == csid
    xml = client.get(f"/cspace-services/media/{csid}", auth=ADMIN).text
    assert f"<blobCsid>{blob}</blobCsid>" in xml and "<workflowState>project</workflowState>" in xml
    assert xml.count("<blobCsid>") == 1


def test_serena_gets_an_uploaded_file_as_the_original_and_every_derivative_at_both_paths(client: TestClient) -> None:
    csid = created(client.post("/cspace-services/media", auth=ADMIN, content=MEDIA_XML))
    blob = upload(client, csid, b"jpeg bytes")
    assert client.get(f"/cspace-services/media/{csid}/blob/content", auth=SERENA).content == b"jpeg bytes"
    for name in DERIVATIVES:
        assert client.get(f"/cspace-services/media/{csid}/blob/derivatives/{name}/content", auth=SERENA).content \
            == b"jpeg bytes"
        assert client.get(f"/cspace-services/blobs/{blob}/derivatives/{name}/content", auth=ADMIN).content \
            == b"jpeg bytes"
    found = client.get("/cspace-services/media", params={"as": f'media_common:blobCsid = "{blob}"'}, auth=SERENA)
    assert f"<csid>{csid}</csid>" in found.text
    blob_xml = client.get(f"/cspace-services/blobs/{blob}", auth=SERENA).text
    assert "<name>20-0501_a.jpg</name>" in blob_xml and "<length>10</length>" in blob_xml


def test_a_file_over_5_mb_isnt_kept(client: TestClient) -> None:
    csid = created(client.post("/cspace-services/media", auth=ADMIN, content=MEDIA_XML))
    blob = upload(client, csid, b"x" * (KEEP_BYTES + 1))
    assert store.blobs[blob]["size"] == KEEP_BYTES + 1
    assert client.get(f"/cspace-services/media/{csid}/blob/content", auth=SERENA).status_code == 404


def test_a_client_may_not_send_blobcsid(client: TestClient) -> None:
    body = MEDIA_XML.replace(b"</title>", b"</title><blobCsid>b-1</blobCsid>")
    assert client.post("/cspace-services/media", auth=ADMIN, content=body).status_code == 400


def test_uploading_to_an_unknown_record_is_404(client: TestClient) -> None:
    r = client.put("/cspace-services/media/nope/blob", auth=ADMIN, files={"file": ("a.jpg", b"x", "image/jpeg")})
    assert r.status_code == 404


def test_objects_relations_and_groups(client: TestClient) -> None:
    client.post("/_fake/seed", json={"set": "bmu"})
    obj = created(client.post("/cspace-services/collectionobjects", auth=ADMIN,
                              content=b"<document><objectNumber>20-0501</objectNumber></document>"))
    media = created(client.post("/cspace-services/media", auth=ADMIN, content=MEDIA_XML))
    rel = (f"<document><subjectCsid>{media}</subjectCsid><subjectDocumentType>Media</subjectDocumentType>"
           f"<objectCsid>{obj}</objectCsid><objectDocumentType>CollectionObject</objectDocumentType></document>")
    created(client.post("/cspace-services/relations", auth=ADMIN, content=rel.encode()))
    found = client.get("/cspace-services/relations", params={"sbj": media, "obj": obj}, auth=ADMIN)
    assert found.text.count("<relation-list-item>") == 1
    group = created(client.post("/cspace-services/groups", auth=ADMIN,
                                content=b"<document><title>Batch 1</title></document>"))
    assert store.groups[group]["title"] == "Batch 1"
    assert client.post("/cspace-services/groups", auth=ADMIN, content=b"<document/>").status_code == 400
    assert client.post("/cspace-services/collectionobjects", auth=("limited", "limited"),
                       content=b"<document/>").status_code == 403


def test_a_sensitive_object_carries_pahmas_fields(client: TestClient) -> None:
    client.post("/_fake/seed", json={"set": "bmu"})
    csid = next(c for c, o in store.objects.items() if o["objectNumber"] == "12-2002")
    xml = client.get(f"/cspace-services/collectionobjects/{csid}", auth=ADMIN).text
    assert "<nagpraStatus>under NAGPRA review</nagpraStatus>" in xml and "restriction" in xml
    deleted = next(c for c, o in store.objects.items() if o["deleted"])
    assert client.get(f"/cspace-services/collectionobjects/{deleted}", auth=ADMIN).status_code == 404


def test_the_location_keeps_the_museums_prefix() -> None:
    r = museum("pahma").post("/ucjeps/cspace-services/media", auth=ADMIN, content=MEDIA_XML)
    assert re.search(r"/ucjeps/cspace-services/media/[0-9a-f-]+$", r.headers["location"])


@pytest.mark.parametrize("lost", ["media", "collectionobjects", "groups", "relations"])
def test_a_lost_response_still_saves_the_record(client: TestClient, lost: str) -> None:
    store.fail_next[f"{lost}_lost"] = 504
    bodies = {"media": MEDIA_XML, "collectionobjects": b"<document><objectNumber>1</objectNumber></document>",
              "groups": b"<document><title>G</title></document>",
              "relations": b"<document><subjectCsid>a</subjectCsid><objectCsid>b</objectCsid></document>"}
    assert client.post(f"/cspace-services/{lost}", auth=ADMIN, content=bodies[lost]).status_code == 504
    table: dict[str, Any] = {"media": store.media, "collectionobjects": store.objects, "groups": store.groups,
             "relations": store.relations}
    assert len(table[lost]) == 1


def test_slow_uploads_and_creates_are_set_per_museum(client: TestClient) -> None:
    assert client.post("/_fake/slow", params={"seconds": 99, "upload_mbps": 2}).json() == \
        {"delay": 30.0, "upload_mbps": 2.0}
    assert store.delay == 30.0
    client.post("/_fake/slow", params={"seconds": 0})
    assert store.delay == 0.0
