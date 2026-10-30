"""Development hooks, under /_fake: not part of CollectionSpace. Each acts on the museum of the request (its host name
or path prefix, as for CollectionSpace's endpoints), except /_fake/reset, which empties every museum's store.

  POST   /_fake/reset              every museum's store empty, failures and slowness cleared
  POST   /_fake/seed               {"set": "bmu"}: add a sample set (seeds.py) to this museum's store
  GET    /_fake/media              this museum's Media records with their kind and access (for a servable list)
  POST   /_fake/media              {"csid", "kind": image|card|pdf|3D, "state"?, "blob"?, "identification"?, "band"?,
                                   "access"?: public|restricted, "museum"?: whose store (else the request's)}: a
                                   Media record with sample files (a record the store already has is kept as it is)
  POST   /_fake/delete/<csid>      soft-delete a Media record (the Media service still returns it)
  POST   /_fake/undelete/<csid>    undo a soft delete
  POST   /_fake/replace/<csid>     replace its file (a record with a Blob gets a new Blob CSID)
  POST   /_fake/restore/<csid>     undo replacing
  POST   /_fake/approve/<csid>     {"approved": false}: change its "Approved for web"
  POST   /_fake/remove-file/<csid> leave the record with no file
  POST   /_fake/unreachable        {"on": true | false}: an outage, every CollectionSpace call answers 503
  POST   /_fake/fail               a failure on demand, JSON (FailRule below); GET lists them, DELETE clears them
  GET    /_fake/calls              the paths of record and file requests, in order
  POST   /_fake/slow               ?seconds=&upload_mbps=: slow creates and uploads
  GET    /_fake/state, /_fake/objects, /_fake/settings, /_fake/users: what the store holds and the controls are set to
  POST   /_fake/delete-term, rename-term, delete-language, rename-language: terms changed in CollectionSpace meanwhile
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from . import bands, samples, seeds, vocab
from .accounts import USER_NOTES, USERS
from .context import museum_of, store_of, stores
from .store import DERIVATIVES, STEPS, Media, Store, new_csid, now

router = APIRouter(prefix="/_fake")


@router.post("/reset")
def reset() -> dict[str, Any]:
    stores.reset()
    return {"ok": True}


class Seed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    set: str


@router.post("/seed")
def seed(body: Seed, request: Request) -> dict[str, Any]:
    s = store_of(request)
    try:
        seeds.seed(s, body.set)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return {"museum": s.museum, "seeded": s.seeded}


# --- Media records (Serena's development hooks)

@router.get("/media")
def list_media(request: Request) -> list[dict[str, Any]]:
    """This museum's Media records: what a mock ETL needs to list the ones with files (F12)."""
    return [{"csid": m.csid, "identificationNumber": m.identification_number, "title": m.title,
             "blobCsid": m.blob or "", "state": m.state, "approvedForWeb": m.approved_for_web,
             "publishTo": m.publish_to, "files": sorted(m.files), "updatedAt": m.updated_at, "kind": m.kind,
             "access": m.access}
            for m in store_of(request).media.values()]


@router.post("/media")
async def add_media(request: Request) -> JSONResponse:
    body: dict[str, Any] = await request.json()
    named = body.get("museum")
    if named is not None and named not in stores:
        raise HTTPException(400, f"unknown museum {named}: one of {', '.join(stores)}")
    s = stores[named] if named else store_of(request)
    existing = s.media.get(body["csid"])
    if existing is not None:
        return JSONResponse({"csid": existing.csid, "files": sorted(existing.files), "kept": True})
    band = body.get("band")
    if band is not None and band not in bands.ORIGINALS:
        raise HTTPException(400, f"unknown band {band}: one of {', '.join(bands.ORIGINALS)}")
    try:
        media = s.add(body["csid"], body.get("kind", "image"), body.get("state", "project"),
                      blob=body.get("blob"), identification_number=body.get("identification"), band=band,
                      access=body.get("access", "public"))
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return JSONResponse({"csid": media.csid, "files": sorted(media.files)})


def _known(s: Store, csid: str) -> Media:
    """A hook's Media record, or a 404 that says what to give (a Blob CSID isn't a Media record's)."""
    media = s.media.get(csid)
    if media is None:
        blob_of = s.media_of_blob(csid)
        hint = (f": that's the Blob of Media record {blob_of.csid}; give the Media CSID" if blob_of
                else ": give a Media CSID the simulator has (POST /_fake/media adds one)")
        raise HTTPException(404, f"No Media record {csid} in {s.museum}{hint}")
    return media


@router.post("/delete/{csid}")
def soft_delete(csid: str, request: Request) -> dict[str, str]:
    media = _known(store_of(request), csid)
    media.state = "deleted"
    media.updated_at = now()
    return {"csid": csid, "state": "deleted"}


@router.post("/undelete/{csid}")
def undelete(csid: str, request: Request) -> dict[str, str]:
    media = _known(store_of(request), csid)
    if media.state == "deleted":
        media.state = "project"
        media.updated_at = now()  # an undelete is a change, as in CollectionSpace
    return {"csid": csid, "state": media.state}


@router.post("/replace/{csid}")
def replace(csid: str, request: Request) -> dict[str, str]:
    media = _known(store_of(request), csid)
    if media.before_replace is None:
        media.before_replace = (media.files, media.blob)
    image = samples.png(shade=32)  # a different image
    media.files = {"content": (image, "image/png"), **{n: (image, "image/png") for n in DERIVATIVES}}
    if media.blob:
        media.blob = new_csid()  # CollectionSpace makes a new Blob for the new file
    media.updated_at = now()
    return {"csid": csid, "replaced": "yes", "blob": media.blob or ""}


@router.post("/restore/{csid}")
def restore(csid: str, request: Request) -> dict[str, str]:
    media = _known(store_of(request), csid)
    if media.before_replace is not None:
        media.files, media.blob = media.before_replace
        media.before_replace = None
        media.updated_at = now()  # pointing the record back at its old Blob is a change
    return {"csid": csid, "blob": media.blob or ""}


@router.post("/approve/{csid}")
async def approve(csid: str, request: Request) -> dict[str, Any]:
    """Set the Media record's "Approved for web", as PAHMA's staff do to take it off the web."""
    media = _known(store_of(request), csid)
    body: dict[str, Any] = await request.json()
    media.approved_for_web = bool(body["approved"])
    media.updated_at = now()
    return {"csid": csid, "approved": media.approved_for_web}


@router.post("/remove-file/{csid}")
def remove_file(csid: str, request: Request) -> dict[str, str]:
    _known(store_of(request), csid).files = {}
    return {"csid": csid, "files": "none"}


@router.post("/unreachable")
async def unreachable(request: Request) -> dict[str, bool]:
    """{"on": true}: an outage, every CollectionSpace call answers 503 and the records are kept; {"on": false} ends
    it."""
    body: dict[str, Any] = await request.json()
    s = store_of(request)
    s.unreachable = bool(body["on"])
    return {"unreachable": s.unreachable}


# --- failures on demand (one shape for both apps, F13)

class FailRule(BaseModel):
    """POST /_fake/fail's body. With `step` (one of STEPS), the rule applies to that step of the BMU's work, and
    `match` to the names it carries (identification number, file name, object number, group title, term); with no
    step, to every request whose path contains `path`. `status`: the HTTP status answered. `effect` ("none" or
    "many", objectSearch and mediaSearch only): what the search finds, instead of a status. `times`: how many
    requests fail (0 = until cleared with DELETE /_fake/fail). `agent`: only requests whose User-Agent starts with it
    (the BMU sends "bmu-worker" for job runs only, so the editor's checks aren't affected)."""

    model_config = ConfigDict(extra="forbid")
    step: str = ""
    path: str = ""
    match: str = ""
    status: int = Field(500, ge=100, le=599)
    effect: Literal["", "none", "many"] = ""
    times: int = Field(1, ge=0)
    agent: str = ""


@router.post("/fail")
def add_failure(rule: FailRule, request: Request) -> Response:
    if rule.step and rule.step not in STEPS:
        return Response(status_code=400, content=f"step is one of {', '.join(sorted(STEPS))}")
    if rule.match and not rule.step:
        return Response(status_code=400, content="match needs a step; to match a request's path, use path")
    if rule.effect and rule.step not in ("objectSearch", "mediaSearch"):
        return Response(status_code=400, content="effect (none or many) is for objectSearch and mediaSearch")
    s = store_of(request)
    s.fail(rule.path, rule.status, rule.times, step=rule.step, match=rule.match, effect=rule.effect,
           agent=rule.agent)
    return JSONResponse({"rules": [r.as_dict() for r in s.rules]})


@router.get("/fail")
def list_failures(request: Request) -> dict[str, Any]:
    return {"rules": [r.as_dict() for r in store_of(request).rules]}


@router.delete("/fail")
def clear_failures(request: Request) -> dict[str, Any]:
    store_of(request).rules.clear()
    return {"rules": []}


@router.get("/calls")
def calls(request: Request) -> list[str]:
    return list(store_of(request).calls)


# --- the BMU's development hooks

@router.post("/slow")
def slow(request: Request, seconds: float = 2.0, upload_mbps: float = 0.0) -> dict[str, float]:
    """Add this many seconds to every create and upload (0 to turn it off), and with upload_mbps receive file uploads
    at about that many MB/s (0 = no limit)."""
    s = store_of(request)
    s.delay = max(0.0, min(seconds, 30.0))
    s.upload_mbps = max(0.0, upload_mbps)
    return {"delay": s.delay, "upload_mbps": s.upload_mbps}


@router.post("/delete-term")
def delete_term(request: Request, name: str, how: str = "deleted") -> Any:
    """A Person or Organization term (by display name) is deleted in CollectionSpace meanwhile: how=deleted
    soft-deletes it, how=gone makes reading it return 404 (purged, or merged away)."""
    if name not in vocab.PEOPLE + vocab.ORGS or how not in ("deleted", "gone"):
        return Response(status_code=400, content="name is a sample term's display name; how is deleted or gone")
    s = store_of(request)
    s.term_states[vocab.short(name)] = how
    return {"deleted": s.term_states}


@router.post("/rename-term")
def rename_term(request: Request, name: str, to: str) -> Any:
    """A Person or Organization term (by its original display name) is renamed in CollectionSpace meanwhile. It keeps
    its short identifier, so its refName changes only in the display name part."""
    if name not in vocab.PEOPLE + vocab.ORGS or not to.strip():
        return Response(status_code=400, content="name is a sample term's original display name; to is its new name")
    s = store_of(request)
    s.term_renames[vocab.short(name)] = to.strip()
    return {"renamed": s.term_renames}


@router.post("/delete-language")
def delete_language(request: Request, code: str) -> Any:
    """A language (by code, e.g. spa) leaves the languages vocabulary."""
    if code not in vocab.LANGUAGES:
        return Response(status_code=400, content=f"code is one of {', '.join(vocab.LANGUAGES)}")
    s = store_of(request)
    s.deleted_languages.add(code)
    return {"deleted": sorted(s.deleted_languages)}


@router.post("/rename-language")
def rename_language(request: Request, code: str, to: str) -> Any:
    """A language (by code, e.g. spa) is renamed in the languages vocabulary."""
    if code not in vocab.LANGUAGES or not to.strip():
        return Response(status_code=400, content="code is a sample language's code; to is its new name")
    s = store_of(request)
    s.language_renames[code] = to.strip()
    return {"renamed": s.language_renames}


@router.get("/state")
def state(request: Request) -> dict[str, Any]:
    s = store_of(request)
    media = {c: {"identificationNumber": m.identification_number, "title": m.title, "blobCsid": m.blob or "",
                 "deleted": m.state == "deleted"} for c, m in s.media.items()}
    return {"museum": s.museum, "objects": s.objects, "media": media, "blobs": s.blobs, "relations": s.relations,
            "groups": s.groups}


@router.get("/objects")
def objects(request: Request) -> list[dict[str, Any]]:
    """The Object records, one line each (object number, what it's for, sensitivity fields)."""
    return sorted(({"objectNumber": o["objectNumber"], "note": o.get("note", ""), "deleted": o.get("deleted", False),
                    **({"sensitivity": o["sensitivity"]} if o.get("sensitivity") else {})}
                   for o in store_of(request).objects.values()), key=lambda o: o["objectNumber"])


@router.get("/settings")
def settings(request: Request) -> dict[str, Any]:
    """What the /_fake controls are set to now, and the sample terms and languages they take (the BMU's Demo tools
    show these)."""
    s = store_of(request)
    return {"museum": museum_of(request), "delay": s.delay, "upload_mbps": s.upload_mbps,
            "rules": [r.as_dict() for r in s.rules], "unreachable": s.unreachable,
            "term_states": {**s.term_states}, "term_renames": {**s.term_renames},
            "deleted_languages": sorted(s.deleted_languages), "language_renames": {**s.language_renames},
            "steps": sorted(STEPS), "people": vocab.PEOPLE, "orgs": vocab.ORGS, "languages": vocab.LANGUAGES,
            "term_names": {vocab.short(n): n for n in vocab.PEOPLE + vocab.ORGS}}


@router.get("/users")
def users() -> list[dict[str, str]]:
    """The people among the simulator's users, with what each is for and its password (the BMU's Demo tools sign in
    as one with a click). A real CollectionSpace has no such endpoint."""
    return [{"user": u, "password": USERS[u], "about": about} for u, about in USER_NOTES.items()]
