"""Sample record sets a client asks for after a reset (F9): POST /_fake/seed {"set": "<name>"}.

The simulator starts empty. Each app seeds the set it needs (its up command and its tests do), so each app's tests see
what they always have; in shared mode both apps' sets are seeded into the same museum.
"""
from __future__ import annotations

from collections.abc import Callable

from .store import Media, Store, new_csid

# The BMU's sample Object records. Most are ordinary; 9-9999 is on two objects, to exercise "matches several objects".
BMU_OBJECTS = [
    ("15-1234", "Ordinary; a Media record with ID 15-1234 already exists"),
    ("12-5678", "Ordinary"),
    ("15-1240", "Ordinary"),
    ("1-2345", "Ordinary"),
    ("9-9999", "Shares its number with another object"),
    ("9-9999", "Shares its number with another object"),
    ("3-1001", "Ordinary"),
    ("3-1002", "Ordinary"),
    ("3-1003.1", "Ordinary; a part number with a dot (filename 3-1003.1_a.jpg)"),
    ("16-4711", "Ordinary"),
]

# Objects PAHMA treats as sensitive, or nearly so (BMU design: Protected files, Per-tenant signals). GET
# collectionobjects/{csid} returns these fields with the element names in the BMU's tenants/pahma.yaml rules.
BMU_SENSITIVE_OBJECTS = [
    ("12-2001", "Sensitive: culturally sensitive, Human Remains department (the public portal hides its images)",
     {"objectStatus": ["culturally sensitive"], "department": "Human Remains"}),
    ("12-2002", "Sensitive: NAGPRA status and a display restriction at the restriction level",
     {"nagpraStatus": "under NAGPRA review",
      "accessRestrictions": [{"type": "display/visual", "level": "restriction"}]}),
    ("12-2003", "Soft signal only: a display restriction at the preference level (a warning, not protected)",
     {"accessRestrictions": [{"type": "display/visual", "level": "preference"}]}),
]


def bmu(store: Store) -> None:
    """The BMU's samples: 14 Objects (three sensitive or nearly, one soft-deleted) and a Media record 15-1234 with no
    file."""
    for number, note in BMU_OBJECTS:
        store.objects[new_csid()] = {"objectNumber": number, "deleted": False, "note": note}
    for number, note, sensitivity in BMU_SENSITIVE_OBJECTS:
        store.objects[new_csid()] = {"objectNumber": number, "deleted": False, "note": note,
                                     "sensitivity": sensitivity}
    # Soft-deleted in CollectionSpace: searches with wf_deleted=false don't find it.
    store.objects[new_csid()] = {"objectNumber": "3-1004", "deleted": True, "note": "Deleted: searches don't find it"}
    csid = new_csid()
    store.media[csid] = Media(csid, identification_number="15-1234")


SETS: dict[str, Callable[[Store], None]] = {"bmu": bmu}


def seed(store: Store, name: str) -> None:
    """Adds a sample set to the store (once: seeding a set again before a reset changes nothing)."""
    if name not in SETS:
        raise ValueError(f"unknown sample set {name}: one of {', '.join(sorted(SETS))}")
    if name in store.seeded:
        return
    SETS[name](store)
    store.seeded.append(name)
