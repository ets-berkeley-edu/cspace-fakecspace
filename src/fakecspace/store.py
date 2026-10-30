"""The simulator's records: one store per museum, kept in memory.

Real CollectionSpace is a separate server for each museum, so a record made through pahma.fakecspace isn't seen
through ucjeps.fakecspace (F8). `stores` holds the five museums' stores; `stores["pahma"]` is the one a request gets
when neither its host name nor its path names a museum.

A Media record is a `Media`. Both styles of access work, because the BMU's and Serena's code and tests grew up with
different simulators: attributes (`media.blob`, `media.files`, Serena's) and the field names CollectionSpace uses
(`media["blobCsid"]`, `media.get("title")`, the BMU's). Assigning a plain dict to `store.media[csid]` makes a Media
from it.
"""
from __future__ import annotations

import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from . import bands, samples

TENANT_IDS = {"bampfa": "11", "botgarden": "12", "cinefiles": "13", "pahma": "14", "ucjeps": "15"}  # synthetic
DEFAULT_MUSEUM = "pahma"
DERIVATIVES = ("Thumbnail", "Small", "Medium", "FullHD", "OriginalJpeg")
# Steps of the BMU's work that a /_fake/fail rule can name (see Rule).
STEPS = frozenset({"media", "upload", "objectSearch", "objectCreate", "relation", "mediaSearch", "group", "termRead"})

FileMap = dict[str, tuple[bytes | None, str]]


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


# CollectionSpace's field name -> Media's attribute, for the dict-style access.
_FIELDS = {"identificationNumber": "identification_number", "title": "title", "blobCsid": "blob", "xml": "xml",
           "deleted": "state"}


@dataclass
class Media:
    csid: str
    state: str = "project"  # CollectionSpace's workflow state; "deleted" when soft-deleted
    # "content" or a derivative -> (bytes, type); None for bytes: the record's band's file of that name (bands.py)
    files: FileMap = field(default_factory=dict)
    blob: str | None = None  # its Blob's CSID (blobCsid)
    publish_to: str = "All"  # media_common's publishTo, a vocabulary term (core CollectionSpace)
    approved_for_web: bool = True  # media_pahma's approvedforweb: what PAHMA's ETL reads
    identification_number: str = ""  # media_common's identificationNumber
    title: str = ""  # media_common's title (the BMU puts the file name there)
    xml: str | None = None  # the record as a client saved it (POST media); returned by GET, with blobCsid set
    updated_at: str = field(default_factory=now)  # collectionspace_core's updatedAt
    # Its files and Blob CSID before its first replace, for /_fake/restore; None if never replaced.
    before_replace: tuple[FileMap, str | None] | None = None
    band: str | None = None  # the size band of its files, or None for the 8x8 samples

    # --- dict-style access, by CollectionSpace's field names
    def _get(self, key: str) -> Any:
        if key == "deleted":
            return self.state == "deleted"
        if key == "blobCsid":
            return self.blob or ""
        return getattr(self, _FIELDS[key])

    def __getitem__(self, key: str) -> Any:
        if key not in self:
            raise KeyError(key)
        return self._get(key)

    def __contains__(self, key: object) -> bool:
        return key in _FIELDS and not (key == "xml" and self.xml is None)

    def get(self, key: str, default: Any = None) -> Any:
        return self._get(key) if key in self else default

    def __setitem__(self, key: str, value: Any) -> None:
        if key == "deleted":
            self.state = "deleted" if value else "project"
        elif key == "blobCsid":
            self.blob = value or None
        else:
            setattr(self, _FIELDS[key], value)

    @classmethod
    def from_fields(cls, csid: str, fields: dict[str, Any]) -> Media:
        media = cls(csid)
        for key, value in fields.items():
            media[key] = value
        return media


class MediaTable(dict[str, Media]):
    """The Media records by CSID; a plain dict assigned to one becomes a Media."""

    def __setitem__(self, csid: str, value: Media | dict[str, Any]) -> None:
        super().__setitem__(csid, value if isinstance(value, Media) else Media.from_fields(csid, value))


@dataclass
class Rule:
    """A failure on demand (/_fake/fail). With a step, it applies to that step of the BMU's work (see STEPS), to
    requests whose names (identification number, file name, object number, group title, term) contain `match`; with
    no step, to every request whose path contains `path`. `agent`: only requests whose User-Agent starts with it
    ("bmu-worker": only job runs). `effect` (objectSearch, mediaSearch): "none" or "many" found, instead of a status.
    `times`: how many requests fail; 0 until cleared."""

    step: str = ""
    path: str = ""
    match: str = ""
    status: int = 500
    effect: str = ""
    times: int = 1
    agent: str = ""
    left: int = 0
    hits: int = 0

    def __post_init__(self) -> None:
        self.left = self.times

    def applies(self, step: str, path: str, names: list[str], agent: str) -> bool:
        if self.step != step or (self.times and self.left <= 0):
            return False
        if self.agent and not agent.startswith(self.agent):
            return False
        if self.path and self.path not in path:
            return False
        return not self.match or any(self.match.lower() in (n or "").lower() for n in names)

    def as_dict(self) -> dict[str, Any]:
        return {"step": self.step, "path": self.path, "match": self.match, "status": self.status,
                "effect": self.effect, "times": self.times, "agent": self.agent, "left": self.left,
                "hits": self.hits}


class Store:
    def __init__(self, museum: str = DEFAULT_MUSEUM) -> None:
        self.museum = museum
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        """Empty: no records, no failures, no slowness (F9: a client seeds the samples it wants)."""
        with self.lock:
            self.objects: dict[str, dict[str, Any]] = {}
            self.media: MediaTable = MediaTable()
            self.blobs: dict[str, dict[str, Any]] = {}  # Blobs made by an upload: name, size, type, media
            self.relations: dict[str, dict[str, str]] = {}
            self.groups: dict[str, dict[str, Any]] = {}
            self.rules: list[Rule] = []  # failures on demand (/_fake/fail)
            self.fail_next: dict[str, int] = {}  # e.g. {"media": 503}: the next call to that service fails once
            self.unreachable = False  # an outage: every CollectionSpace call answers 503, the records kept
            self.perm_overrides: dict[str, dict[str, str]] = {}  # user -> {resource: actions}: permissions changed
            self.role_overrides: dict[str, list[str]] = {}  # user -> role names: roles changed
            self.inactive: set[str] = set()  # users whose account is inactive: every request of theirs answers 409
            self.searches: list[tuple[str, str | None]] = []  # (service, searched value), to test lookup caching
            # Authority terms deleted meanwhile, by short identifier: "deleted" (soft-deleted) or "gone" (404).
            self.term_states: dict[str, str] = {}
            self.term_renames: dict[str, str] = {}  # short identifier -> its new display name
            self.deleted_languages: set[str] = set()
            self.language_renames: dict[str, str] = {}  # language code -> its new display name
            self.term_reads: list[str] = []  # short identifiers read one by one
            self.calls: list[str] = []  # paths of the record and file requests answered or refused after sign-in
            self.requests: deque[dict[str, str]] = deque(maxlen=5000)  # {"user", "path"} of every signed-in request
            self.delay = 0.0  # seconds added to every create or upload (/_fake/slow)
            self.upload_mbps = 0.0  # file uploads are received at this many MB/s (0 = no limit)
            self.seeded: list[str] = []  # the sample sets seeded since the last reset

    # --- Serena's style of adding records
    def add(self, csid: str, kind: str = "image", state: str = "project", shade: int = 128,
            blob: str | None = None, identification_number: str | None = None, band: str | None = None) -> Media:
        """A Media record with sample files (an 8x8 PNG, a one-page PDF or a one-box X3D scene), or with files of
        about a real one's size for a size band (images only)."""
        files: FileMap
        if band is not None and kind not in ("image", "card"):
            raise ValueError(f"a size band is for images only, not {kind}")
        if band is not None:
            bands.prepare(band)  # made in the background, so the first request for the file waits less
            files = {name: (None, "image/jpeg") for name in ("content", *DERIVATIVES)}
        elif kind in ("image", "card"):
            image = samples.png(shade=shade)
            files = {"content": (image, "image/png"), **{name: (image, "image/png") for name in DERIVATIVES}}
        elif kind == "pdf":
            files = {"content": (samples.pdf(), "application/pdf")}
        elif kind == "3D":
            files = {"content": (samples.x3d(), "model/x3d+xml")}
        else:
            raise ValueError(f"unknown kind {kind}")
        with self.lock:
            # A synthetic identification number unless one is given: 2026.1.1, 2026.1.2, ...
            number = identification_number if identification_number is not None else f"2026.1.{len(self.media) + 1}"
            media = Media(csid, state, files, blob, identification_number=number, band=band)
            self.media[csid] = media
        return media

    def media_of_blob(self, blob: str) -> Media | None:
        with self.lock:
            return next((m for m in self.media.values() if m.blob == blob), None)

    def fail(self, path: str = "", status: int = 500, times: int = 1, *, step: str = "", match: str = "",
             effect: str = "", agent: str = "") -> Rule:
        """Adds a failure on demand (see Rule); what POST /_fake/fail does."""
        rule = Rule(step=step, path=path, match=match, status=status, effect=effect, times=max(0, times), agent=agent)
        with self.lock:
            self.rules.append(rule)
        return rule

    def take_rule(self, step: str, path: str, names: list[str], agent: str) -> Rule | None:
        """The first rule that applies to this request, counted as used."""
        with self.lock:
            for rule in self.rules:
                if rule.applies(step, path, names, agent):
                    rule.left -= 1
                    rule.hits += 1
                    if rule.times and rule.left <= 0:
                        self.rules.remove(rule)  # used up
                    return rule
        return None


class Stores(dict[str, Store]):
    """Every museum's store."""

    def __init__(self) -> None:
        super().__init__({museum: Store(museum) for museum in TENANT_IDS})

    def reset(self) -> None:
        for store in self.values():
            store.reset()


def new_csid() -> str:
    return str(uuid.uuid4())
