"""Failures on demand: one shape for both apps (F13), searches, and the BMU's term hooks."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fakecspace.app import store

from .conftest import ADMIN, SERENA

WORKER = {"user-agent": "bmu-worker/1"}


def fail(client: TestClient, **rule: object) -> list[dict[str, object]]:
    r = client.post("/_fake/fail", json=rule)
    assert r.status_code == 200, r.text
    return r.json()["rules"]


def test_a_path_rule_fails_matching_requests_the_given_number_of_times(client: TestClient) -> None:
    client.post("/_fake/media", json={"csid": "m-1"})
    fail(client, path="/blob/content", status=502, times=2)
    for _ in range(2):
        assert client.get("/cspace-services/media/m-1/blob/content", auth=SERENA).status_code == 502
    assert client.get("/cspace-services/media/m-1/blob/content", auth=SERENA).status_code == 200
    assert client.get("/_fake/fail").json() == {"rules": []}  # used up


def test_times_0_fails_until_cleared(client: TestClient) -> None:
    client.post("/_fake/media", json={"csid": "m-1"})
    fail(client, path="/media/", status=500, times=0)
    for _ in range(3):
        assert client.get("/cspace-services/media/m-1", auth=SERENA).status_code == 500
    client.delete("/_fake/fail")
    assert client.get("/cspace-services/media/m-1", auth=SERENA).status_code == 200


def test_the_python_shortcut_keeps_serenas_order(client: TestClient) -> None:
    client.post("/_fake/media", json={"csid": "m-1"})
    store.fail("/media/m-1", 503)
    assert client.get("/cspace-services/media/m-1", auth=SERENA).status_code == 503


def test_a_step_rule_matches_names_and_by_default_any_client(client: TestClient) -> None:
    fail(client, step="media", match="20-05", status=413)
    body = b"<document><identificationNumber>20-0501</identificationNumber></document>"
    other = b"<document><identificationNumber>1-1</identificationNumber></document>"
    assert client.post("/cspace-services/media", auth=ADMIN, content=other).status_code == 201
    assert client.post("/cspace-services/media", auth=ADMIN, content=body).status_code == 413
    assert client.post("/cspace-services/media", auth=ADMIN, content=body).status_code == 201


def test_an_agent_rule_affects_only_that_client(client: TestClient) -> None:
    fail(client, step="objectCreate", status=500, agent="bmu-worker")
    body = b"<document><objectNumber>1-1</objectNumber></document>"
    assert client.post("/cspace-services/collectionobjects", auth=ADMIN, content=body).status_code == 201
    assert client.post("/cspace-services/collectionobjects", auth=ADMIN, content=body,
                       headers=WORKER).status_code == 500


@pytest.mark.parametrize(("effect", "count"), [("none", 0), ("many", 2)])
def test_a_search_can_find_none_or_many(client: TestClient, effect: str, count: int) -> None:
    client.post("/_fake/seed", json={"set": "bmu"})
    fail(client, step="objectSearch", effect=effect, match="1-2345")
    r = client.get("/cspace-services/collectionobjects", auth=ADMIN,
                   params={"as": 'collectionobjects_common:objectNumber = "1-2345"', "wf_deleted": "false"})
    assert r.text.count("<list-item>") == count


@pytest.mark.parametrize("rule", [
    {"step": "nope"},
    {"match": "x"},  # Serena's old shape: a path goes in path
    {"step": "media", "effect": "none"},
])
def test_bad_rules_are_refused(client: TestClient, rule: dict[str, object]) -> None:
    assert client.post("/_fake/fail", json=rule).status_code == 400


@pytest.mark.parametrize("rule", [{"status": 99}, {"times": -1}, {"count": 1}, {"client": "any"}])
def test_unknown_or_out_of_range_fields_are_refused(client: TestClient, rule: dict[str, object]) -> None:
    assert client.post("/_fake/fail", json=rule).status_code == 422


def test_the_rules_are_listed_with_their_hits(client: TestClient) -> None:
    client.post("/_fake/media", json={"csid": "m-1"})
    fail(client, path="/media/m-1", status=500, times=3)
    client.get("/cspace-services/media/m-1", auth=SERENA)
    [rule] = client.get("/_fake/fail").json()["rules"]
    assert rule["hits"] == 1 and rule["left"] == 2


def test_media_searches(client: TestClient) -> None:
    client.post("/_fake/seed", json={"set": "bmu"})
    client.post("/_fake/media", json={"csid": "m-1", "blob": "b-1"})
    client.post("/_fake/delete/m-1")

    def search(query: str | None, **params: str) -> str:
        if query is not None:
            params["as"] = query
        r = client.get("/cspace-services/media", params=params, auth=ADMIN)
        assert r.status_code == 200, r.text
        return r.text

    assert "<identificationNumber>15-1234</identificationNumber>" in search('media_common:identificationNumber = '
                                                                            '"15-1234"')
    assert "<csid>m-1</csid>" in search('media_common:blobCsid="b-1"')  # without wf_deleted, deleted ones too
    assert "<csid>m-1</csid>" not in search('media_common:blobCsid="b-1"', wf_deleted="false")
    assert "<totalItems>1</totalItems>" in search(None, wf_deleted="false")
    bad = client.get("/cspace-services/media", params={"as": 'media_common:color = "red"'}, auth=ADMIN)
    assert bad.status_code == 400


def test_terms_languages_and_dates(client: TestClient) -> None:
    people = client.get("/cspace-services/personauthorities/urn:cspace:name(person)/items",
                        params={"pt": "freund"}, auth=ADMIN).text
    assert "Leslie Freund" in people and "name(7475)" in people
    client.post("/_fake/rename-term", params={"name": "Leslie Freund", "to": "Leslie F."})
    term = client.get("/cspace-services/personauthorities/urn:cspace:name(person)/items/urn:cspace:name(7475)",
                      auth=ADMIN).text
    assert "Leslie F." in term and "pahma.cspace.berkeley.edu" in term
    client.post("/_fake/delete-term", params={"name": "Leslie Freund", "how": "gone"})
    assert client.get("/cspace-services/personauthorities/urn:cspace:name(person)/items/urn:cspace:name(7475)",
                      auth=ADMIN).status_code == 404
    client.post("/_fake/delete-language", params={"code": "spa"})
    languages = client.get("/cspace-services/vocabularies/urn:cspace:name(languages)/items", auth=ADMIN).text
    assert "Spanish" not in languages and "English" in languages
    date = client.get("/cspace-services/structureddates", params={"displayDate": "circa 1920s"}, auth=ADMIN).text
    assert "<dateEarliestSingleYear>1920</dateEarliestSingleYear>" in date and "approximate" in date
    assert client.get("/cspace-services/structureddates", params={"displayDate": "someday"},
                      auth=ADMIN).status_code == 400
    assert "Local Persons" in client.get("/cspace-services/personauthorities", auth=ADMIN).text
    fail(client, step="termRead", match="7475", status=500)
