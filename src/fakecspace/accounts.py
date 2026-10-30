"""The simulator's accounts, their permissions and their roles. All synthetic: each password is its user name, which
is fine only because the simulator never holds real data.

The BMU's users (staff and interns, design doc "Roles") and Serena's (its read-only service account, and admins
for the admin app) are merged; `admin` is in both and has both apps' roles (F0b).
"""
from __future__ import annotations

from .store import TENANT_IDS, Store

# user -> password
USERS = {
    "admin": "admin",  # BMU staff with every permission; a Serena admin of every museum
    "limited": "limited",  # BMU staff who can't create Objects or groups
    "reader": "reader",  # can read everything but has neither BMU role, so the BMU refuses the sign-in
    "intern": "intern",  # a BMU intern: the BMU_Intern role and no permissions at all
    "newstaff": "newstaff",  # has the BMU_Staff role but can only read, so the BMU refuses the sign-in
    "bmureader": "bmureader",  # the BMU's own read-only account (BMU_Reader role); not a person
    "serena": "serena",  # Serena's read-only service account
    "pahma-admin": "pahma-admin",  # a Serena admin of PAHMA only
    "viewer": "viewer",  # can sign in to Serena's admin app but is no museum's admin
}
# Serena's admin app accounts, and the museums each is an admin of (the role Serena_Admin in that museum's tenant).
ADMINS = {user: USERS[user] for user in ("admin", "pahma-admin", "viewer")}
ADMIN_MUSEUMS: dict[str, set[str]] = {"admin": set(TENANT_IDS), "pahma-admin": {"pahma"}, "viewer": set()}

RESOURCES = ("media", "relations", "collectionobjects", "groups", "personauthorities", "orgauthorities",
             "vocabularies", "structureddates")
_ACTIONS = {"admin": "CRUDL", "limited": "CRUDL", "reader": "RL", "intern": "", "newstaff": "RL",
            "bmureader": "RL", "serena": "RL", "pahma-admin": "RL", "viewer": "RL"}

# Role names without the ROLE_<tenant id>_ prefix.
_ROLES = {
    "admin": ["TENANT_ADMINISTRATOR", "TENANT_READER", "BMU_STAFF"],
    "limited": ["TENANT_READER", "BMU_STAFF"],
    "reader": ["TENANT_READER"],
    "intern": ["BMU_INTERN"],
    "newstaff": ["TENANT_READER", "BMU_STAFF"],
    "bmureader": ["BMU_READER"],
    "serena": ["TENANT_READER"],
    "pahma-admin": ["TENANT_READER"],
    "viewer": ["TENANT_READER"],
}

# What each person is for, shown by the BMU's Demo tools ("Sign in as"); not the service accounts.
USER_NOTES = {
    "admin": "Staff with every permission",
    "limited": "Staff who can't create Objects or groups",
    "intern": "Intern: no CollectionSpace permissions",
    "newstaff": "Staff role without the permissions: sign-in refused",
    "reader": "Neither BMU role: sign-in refused",
}


def perms_for(store: Store, user: str) -> dict[str, str]:
    """The user's actions on each resource, as accountperms answers (C, R, U, D, L)."""
    perms = {resource: _ACTIONS[user] for resource in RESOURCES}
    if user == "limited":
        perms["collectionobjects"] = "RL"
        perms["groups"] = "RL"
    perms.update(store.perm_overrides.get(user, {}))
    return perms


def roles_for(store: Store, user: str) -> list[str]:
    """The user's role names in the store's museum's tenant, e.g. ROLE_14_BMU_STAFF."""
    if user in store.role_overrides:
        return list(store.role_overrides[user])
    tenant = TENANT_IDS[store.museum]
    names = list(_ROLES[user])
    if store.museum in ADMIN_MUSEUMS.get(user, set()):
        names.append("SERENA_ADMIN")
    return [f"ROLE_{tenant}_{name}" for name in names]
