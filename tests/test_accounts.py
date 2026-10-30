"""Sign-in, permissions and roles: the BMU's and Serena's accounts merged (F0b)."""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from fakecspace.accounts import ADMINS, USERS
from fakecspace.app import store

from .conftest import ADMIN, SERENA, museum


def roles(client: TestClient, auth: tuple[str, str]) -> tuple[str, list[str]]:
    r = client.get("/cspace-services/accounts/0/accountroles", auth=auth)
    assert r.status_code == 200, r.text
    tenant = re.search(r"<tenantId>(\d+)</tenantId>", r.text)
    assert tenant
    return tenant.group(1), re.findall(r"<roleName>([^<]+)</roleName>", r.text)


def test_every_password_is_the_user_name() -> None:
    assert all(user == password for user, password in USERS.items())
    assert set(ADMINS) <= set(USERS)


@pytest.mark.parametrize("auth", [("admin", "wrong"), ("nobody", "nobody"), None])
def test_a_wrong_sign_in_is_refused(client: TestClient, auth: tuple[str, str] | None) -> None:
    r = client.get("/cspace-services/accounts/0/accountroles", auth=auth)
    assert r.status_code == 401 and "Basic" in r.headers["www-authenticate"]


def test_pahma_is_tenant_14_and_admin_has_both_apps_roles(client: TestClient) -> None:
    tenant, names = roles(client, ADMIN)
    assert tenant == "14"
    assert {"ROLE_14_TENANT_ADMINISTRATOR", "ROLE_14_BMU_STAFF", "ROLE_14_SERENA_ADMIN"} <= set(names)


def test_serena_admins_are_admins_only_of_their_museums() -> None:
    assert "ROLE_15_SERENA_ADMIN" in roles(museum("ucjeps"), ADMIN)[1]
    assert roles(museum("ucjeps"), ("pahma-admin", "pahma-admin"))[1] == ["ROLE_15_TENANT_READER"]
    assert "ROLE_14_SERENA_ADMIN" in roles(museum("pahma"), ("pahma-admin", "pahma-admin"))[1]
    assert roles(museum("pahma"), ("viewer", "viewer"))[1] == ["ROLE_14_TENANT_READER"]
    assert roles(museum("pahma"), SERENA)[1] == ["ROLE_14_TENANT_READER"]


def test_the_bmu_roles(client: TestClient) -> None:
    assert roles(client, ("intern", "intern"))[1] == ["ROLE_14_BMU_INTERN"]
    assert roles(client, ("limited", "limited"))[1] == ["ROLE_14_TENANT_READER", "ROLE_14_BMU_STAFF"]
    assert roles(client, ("bmureader", "bmureader"))[1] == ["ROLE_14_BMU_READER"]


def test_roles_can_be_changed_for_a_test(client: TestClient) -> None:
    store.role_overrides["admin"] = ["ROLE_14_TENANT_READER"]
    assert roles(client, ADMIN)[1] == ["ROLE_14_TENANT_READER"]
    store.fail_next["accountroles"] = 500
    assert client.get("/cspace-services/accounts/0/accountroles", auth=ADMIN).status_code == 500


def test_permissions(client: TestClient) -> None:
    def perms(user: str) -> dict[str, str]:
        r = client.get("/cspace-services/accounts/0/accountperms", auth=(user, user))
        return dict(re.findall(r"<resourceName>(\w+)</resourceName><actionGroup>(\w*)</actionGroup>", r.text))

    assert perms("admin")["collectionobjects"] == "CRUDL"
    assert perms("limited")["collectionobjects"] == "RL" and perms("limited")["media"] == "CRUDL"
    assert perms("intern")["media"] == ""
    assert perms("serena")["media"] == "RL"
    store.perm_overrides["admin"] = {"media": "RL"}
    assert perms("admin")["media"] == "RL"


def test_a_permission_missing_is_403(client: TestClient) -> None:
    client.post("/_fake/media", json={"csid": "m-1"})
    assert client.get("/cspace-services/media/m-1", auth=("intern", "intern")).status_code == 403
    assert client.post("/cspace-services/media", auth=SERENA, content=b"<document/>").status_code == 403


def test_an_inactive_account_gets_409(client: TestClient) -> None:
    store.inactive.add("limited")
    assert client.get("/cspace-services/accounts/0/accountperms", auth=("limited", "limited")).status_code == 409
    assert client.get("/cspace-services/accounts/0/accountperms", auth=ADMIN).status_code == 200


def test_requests_are_recorded_with_their_user(client: TestClient) -> None:
    client.get("/cspace-services/accounts/0/accountperms", auth=ADMIN)
    client.get("/cspace-services/media", auth=SERENA)
    assert [r["user"] for r in store.requests] == ["admin", "serena"]
    assert store.calls == ["/cspace-services/media"]  # record and file requests only


def test_users_lists_the_people_for_the_bmu_demo_tools(client: TestClient) -> None:
    listed = {u["user"]: u["password"] for u in client.get("/_fake/users").json()}
    assert listed == {u: u for u in ("admin", "limited", "intern", "newstaff", "reader")}
