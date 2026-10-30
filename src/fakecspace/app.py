"""A small simulated CollectionSpace services API, for development and tests. It is not CollectionSpace: behaviour
against the real server must be confirmed on a test tenant.

It implements what the Bulk Media Uploader (BMU) and Serena (the media server) call:
- the signed-in account: accounts/0/accountperms and accounts/0/accountroles
- searches: collectionobjects, media (by identificationNumber, title or blobCsid), groups, relations, authority terms
  and the languages vocabulary, and the date parser (structureddates)
- records: GET, and POST for Media, Objects, Relations and groups; PUT media/<csid>/blob attaches a file
- files: media/<csid>/blob/content, media/<csid>/blob/derivatives/<name>/content, blobs/<csid>, and
  blobs/<csid>/derivatives/<name>/content
and development hooks under /_fake (hooks.py). State is in memory, one store per museum (store.py).

Run: uvicorn fakecspace.app:app --port 8180
Each museum is told apart by the host name it's called by (pahma.fakecspace) or a path prefix (/pahma/...); PAHMA when
neither names one. Accounts and their roles: accounts.py (synthetic; each password is the user name).
"""
from __future__ import annotations

import asyncio
import base64
import re
import secrets
from collections.abc import Iterable
from typing import Any
from xml.sax.saxutils import escape

from defusedxml import ElementTree as SafeET
from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import Response, StreamingResponse

from . import __version__, bands, hooks, vocab
from .accounts import ADMINS, USERS, perms_for, roles_for
from .context import museum_of, museum_of_scope, store, store_of, stores
from .store import DERIVATIVES, TENANT_IDS, Media, Rule, Store, new_csid, now

__all__ = ["ADMINS", "USERS", "app", "museum_of", "store", "stores"]

app = FastAPI(title="Fake CollectionSpace (development only)", version=__version__, docs_url=None, redoc_url=None,
              openapi_url=None)

KEEP_BYTES = 5 * 1024 * 1024  # an uploaded file larger than this isn't kept: the record then has no file (F11)
_LIST = '<ns2:abstract-common-list xmlns:ns2="http://collectionspace.org/services/jaxb">'


# --- sign-in, permissions and failures on demand

def _login(request: Request) -> tuple[str, str] | None:
    scheme, _, encoded = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "basic":
        return None
    try:
        user, _, password = base64.b64decode(encoded).decode().partition(":")
    except ValueError:
        return None
    return user, password


def _user(request: Request) -> str | None:
    """The signed-in user, if the sign-in is right (the request is then recorded in the museum's `requests`)."""
    login = _login(request)
    if login is None or not secrets.compare_digest(USERS.get(login[0], "\0"), login[1]):
        return None
    store_of(request).requests.append({"user": login[0], "path": request.url.path})
    return login[0]


def _deny() -> Response:
    return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="org.collectionspace.services"'})


def _gate(request: Request, resource: str, action: str) -> Response | None:
    """The refusal a request gets, if any: no sign-in (401), no permission (403), an outage (503), a fail_next for the
    resource, or a /_fake/fail rule with no step whose path the request's contains."""
    user = _user(request)
    if user is None:
        return _deny()
    s = store_of(request)
    s.calls.append(request.url.path)
    if action not in perms_for(s, user)[resource]:
        return Response(status_code=403)
    if s.unreachable:
        return Response(status_code=503)
    if (status := s.fail_next.pop(resource, None)):
        return Response(status_code=status)
    if (rule := s.take_rule("", request.url.path, [], request.headers.get("user-agent", ""))) is not None:
        return Response(status_code=rule.status)
    return None


def _rule(request: Request, step: str, names: list[str]) -> Rule | None:
    return store_of(request).take_rule(step, request.url.path, names, request.headers.get("user-agent", ""))


def _fail(request: Request, step: str, names: list[str]) -> Response | None:
    """The error a /_fake/fail rule for this step asks for, if one applies."""
    rule = _rule(request, step, names)
    return Response(status_code=rule.status) if rule else None


def _lost(s: Store, service: str) -> Response | None:
    """fail_next {"<service>_lost": 504} (media, media_blob, collectionobjects, groups, relations): the record is
    saved but the response is lost, as after a gateway timeout."""
    status = s.fail_next.pop(f"{service}_lost", None)
    return None if status is None else Response(status_code=status)


# --- XML

def _xml(body: str) -> Response:
    return Response(content='<?xml version="1.0" encoding="UTF-8"?>\n' + body, media_type="application/xml")


def _field(xml: bytes, name: str) -> str:
    """The first element of that local name in a client's XML, its text stripped ("" if none)."""
    root = SafeET.fromstring(xml)
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1].split(":")[-1].lower() == name.lower():
            return (el.text or "").strip()
    return ""


def _created(request: Request, service: str, csid: str) -> Response:
    base = str(request.base_url).rstrip("/")
    prefix = f"/{request.scope['fake_museum']}" if request.scope.get("fake_museum") else ""
    return Response(status_code=201, headers={"Location": f"{base}{prefix}/cspace-services/{service}/{csid}"})


def _core(media: Media) -> str:
    return ('<ns2:collectionspace_core xmlns:ns2="http://collectionspace.org/collectionspace_core/">'
            f"<workflowState>{media.state}</workflowState><updatedAt>{media.updated_at}</updatedAt>"
            "</ns2:collectionspace_core>")


def media_xml(s: Store, media: Media) -> str:
    """A Media record as GET media/<csid> answers: as a client saved it (with the blobCsid CollectionSpace set), or,
    for a record made with the hooks, the fields Serena reads."""
    if media.xml:
        body = re.sub(r"<\?xml[^>]*\?>", "", media.xml).strip()
        body = re.sub(r"<blobCsid>[^<]*</blobCsid>", "", body)
        body = re.sub(r"(</[\w:]*media_common>)", f"<blobCsid>{media.blob or ''}</blobCsid>\\1", body, count=1)
        if "collectionspace_core" not in body:
            body = re.sub(r"(</document>)\s*$", _core(media) + r"\1", body, count=1)
        return body
    publish_to = (f"urn:cspace:{vocab.domain(s)}:vocabularies:name(publishto):item:name({media.publish_to.lower()})"
                  f"'{media.publish_to}'")
    return ('<document name="media"><ns2:media_common xmlns:ns2="http://collectionspace.org/services/media">'
            f"<csid>{media.csid}</csid>"
            f"<identificationNumber>{escape(media.identification_number)}</identificationNumber>"
            + (f"<title>{escape(media.title)}</title>" if media.title else "")
            + f"<blobCsid>{media.blob or ''}</blobCsid>"
            f"<publishToList><publishTo>{escape(publish_to)}</publishTo></publishToList></ns2:media_common>"
            f'<ns2:media_{s.museum} xmlns:ns2="http://collectionspace.org/services/media/local/{s.museum}">'
            f"<approvedforweb>{str(media.approved_for_web).lower()}</approvedforweb></ns2:media_{s.museum}>"
            + _core(media) + "</document>")


# --- the signed-in account

@app.get("/cspace-services/accounts/0/accountperms")
def accountperms(request: Request) -> Response:
    user = _user(request)
    if not user:
        return _deny()
    perms = "".join(f"<permission><resourceName>{r}</resourceName><actionGroup>{a}</actionGroup></permission>"
                    for r, a in perms_for(store_of(request), user).items())
    return _xml('<ns2:account_permission xmlns:ns2="http://collectionspace.org/services/authorization/perms">'
                f"<account><userId>{user}</userId></account>{perms}</ns2:account_permission>")


@app.get("/cspace-services/accounts/0/accountroles")
def accountroles(request: Request) -> Response:
    """The signed-in account's roles in this museum's tenant, shaped like CollectionSpace's. fail_next
    {"accountroles": 500} fails the next call."""
    import uuid

    user = _user(request)
    if not user:
        return _deny()
    s = store_of(request)
    if (status := s.fail_next.pop("accountroles", None)):
        return Response(status_code=status)
    roles = "".join(f"<role><roleRelationshipId>{uuid.uuid5(uuid.NAMESPACE_URL, user + r)}</roleRelationshipId>"
                    f"<roleId>{uuid.uuid5(uuid.NAMESPACE_URL, r)}</roleId><roleName>{escape(r)}</roleName></role>"
                    for r in roles_for(s, user))
    return _xml('<ns2:account_role xmlns:ns2="http://collectionspace.org/services/authorization"><account>'
                f"<accountId>{uuid.uuid5(uuid.NAMESPACE_URL, 'account-' + user)}</accountId>"
                f"<screenName>{user}</screenName><userId>{user}</userId>"
                f"<tenantId>{TENANT_IDS[s.museum]}</tenantId></account>{roles}</ns2:account_role>")


# --- searches

_AS = re.compile(r'^\s*\w+:(\w+)\s*=\s*"((?:[^"\\]|\\.)*)"\s*$')


def _search(request: Request, rows: Iterable[tuple[str, Any]], fields: tuple[str, ...], service: str,
            step: str) -> Response:
    """An advanced search, as=<part>:<field> = "<value>" on one of fields (all records without as). wf_deleted=false
    leaves out soft-deleted records, as in CollectionSpace. List items carry every field."""
    if (refused := _gate(request, service, "R")):
        return refused
    query = request.query_params.get("as")
    field = value = None
    if query is not None:
        m = _AS.match(query)
        if not m or m.group(1) not in fields:
            return Response(status_code=400, content=f"search by one of {', '.join(fields)}")
        field, value = m.group(1), m.group(2).replace('\\"', '"')
    if (rule := _rule(request, step, [value or ""])) is not None:
        shown = field or fields[0]
        if rule.effect == "none":
            return _xml(f"{_LIST}<totalItems>0</totalItems></ns2:abstract-common-list>")
        if rule.effect == "many":
            items = "".join(f"<list-item><csid>{new_csid()}</csid><{shown}>{escape(value or '')}</{shown}></list-item>"
                            for _ in range(2))
            return _xml(f"{_LIST}<totalItems>2</totalItems>{items}</ns2:abstract-common-list>")
        return Response(status_code=rule.status)
    store_of(request).searches.append((service, value))
    live_only = request.query_params.get("wf_deleted") == "false"
    found = [(c, rec) for c, rec in rows
             if not (live_only and rec.get("deleted")) and (field is None or (rec.get(field) or "") == value)]
    items = "".join(f"<list-item><csid>{c}</csid>"
                    + "".join(f"<{f}>{escape(str(rec.get(f) or ''))}</{f}>" for f in fields) + "</list-item>"
                    for c, rec in found)
    return _xml(f"{_LIST}<totalItems>{len(found)}</totalItems>{items}</ns2:abstract-common-list>")


@app.get("/cspace-services/collectionobjects")
def search_objects(request: Request) -> Response:
    return _search(request, list(store_of(request).objects.items()), ("objectNumber",), "collectionobjects",
                   "objectSearch")


@app.get("/cspace-services/media")
def search_media(request: Request) -> Response:
    return _search(request, list(store_of(request).media.items()), ("identificationNumber", "title", "blobCsid"),
                   "media", "mediaSearch")


@app.get("/cspace-services/groups")
def search_groups(request: Request) -> Response:
    return _search(request, list(store_of(request).groups.items()), ("title",), "groups", "group")


def _page(items: list[Any], request: Request, default: int = 40) -> list[Any]:
    """One page of a list, as CollectionSpace pages it: pgSz=0 means every item."""
    size = int(request.query_params.get("pgSz") or default)
    return items if size == 0 else items[:size]


@app.get("/cspace-services/{service}/urn:cspace:name({vocabulary})/items")
def search_terms(service: str, vocabulary: str, request: Request) -> Response:
    import uuid

    s = store_of(request)
    if service == "vocabularies" and vocabulary == "languages":
        if (refused := _gate(request, "vocabularies", "R")):
            return refused
        codes = _page([c for c in vocab.LANGUAGES if c not in s.deleted_languages], request)
        items = "".join(f"<list-item><csid>{uuid.uuid5(uuid.NAMESPACE_URL, c)}</csid><shortIdentifier>{c}"
                        f"</shortIdentifier><displayName>{escape(vocab.language_name(s, c))}</displayName>"
                        f"<refName>{escape(vocab.language_ref(s, c))}</refName></list-item>" for c in codes)
        return _xml(f"{_LIST}{items}</ns2:abstract-common-list>")
    if service not in ("personauthorities", "orgauthorities"):
        return Response(status_code=404)
    if (refused := _gate(request, service, "R")):
        return refused
    q = request.query_params.get("pt", "").lower()
    matches = [n for n in vocab.term_names(service)
               if q in vocab.shown(s, n).lower() and vocab.short(n) not in s.term_states]  # wf_deleted=false
    items = "".join(f"<list-item><csid>{uuid.uuid5(uuid.NAMESPACE_URL, n)}</csid>"
                    f"<termDisplayName>{escape(vocab.shown(s, n))}</termDisplayName>"
                    f"<refName>{escape(vocab.ref(s, service, vocabulary, n))}</refName></list-item>"
                    for n in _page(matches, request))
    return _xml(f"{_LIST}<totalItems>{len(matches)}</totalItems>{items}</ns2:abstract-common-list>")


@app.get("/cspace-services/{service}/urn:cspace:name({vocabulary})/items/urn:cspace:name({short})")
def get_term(service: str, vocabulary: str, short: str, request: Request) -> Response:
    """One authority term by short identifier. A soft-deleted term is still read, with workflow state deleted, as
    CollectionSpace does."""
    if service not in ("personauthorities", "orgauthorities"):
        return Response(status_code=404)
    s = store_of(request)
    s.term_reads.append(short)
    if (refused := _gate(request, service, "R")):
        return refused
    name = next((n for n in vocab.term_names(service) if vocab.short(n) == short), None)
    if (failed := _fail(request, "termRead", [short, name or ""])) is not None:
        return failed
    state = s.term_states.get(short, "")
    if not name or state == "gone":
        return Response(status_code=404)
    doc, ns, group = (("persons", "person", "personTermGroup") if service == "personauthorities"
                      else ("organizations", "organization", "orgTermGroup"))
    common = f"{doc}_common"
    return _xml(f'<document name="{doc}"><ns2:{common} xmlns:ns2="http://collectionspace.org/services/{ns}">'
                f"<shortIdentifier>{escape(short)}</shortIdentifier>"
                f"<refName>{escape(vocab.ref(s, service, vocabulary, name))}</refName>"
                f"<{group}List><{group}><termDisplayName>{escape(vocab.shown(s, name))}</termDisplayName></{group}>"
                f"</{group}List></ns2:{common}>"
                '<ns2:collectionspace_core xmlns:ns2="http://collectionspace.org/collectionspace_core/">'
                f"<workflowState>{'deleted' if state == 'deleted' else 'project'}</workflowState>"
                "</ns2:collectionspace_core></document>")


@app.get("/cspace-services/structureddates")
def structured_dates(request: Request) -> Response:
    if not _user(request):
        return _deny()
    group = vocab.parse_date(store_of(request), request.query_params.get("displayDate", ""))
    if group is None:
        return Response(status_code=400)
    fields = "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in group.items())
    return _xml('<ns2:structureddate_common xmlns:ns2="http://collectionspace.org/services/structureddate">'
                f"{fields}</ns2:structureddate_common>")


# --- Media records and their files

def _media_names(s: Store, csid: str) -> list[str]:
    """What a /_fake/fail rule's match is compared with for a Media record: its number, title and file name."""
    media = s.media.get(csid)
    blob = next((b for b in s.blobs.values() if b.get("media") == csid), {})
    return [media.identification_number if media else "", media.title if media else "", blob.get("name") or ""]


@app.post("/cspace-services/media")
async def create_media(request: Request) -> Response:
    if (refused := _gate(request, "media", "C")):
        return refused
    body = await request.body()
    if _field(body, "blobCsid"):
        return Response(status_code=400)  # a client must not send blobCsid; the file is attached with PUT .../blob
    number, title = _field(body, "identificationNumber"), _field(body, "title")
    if (failed := _fail(request, "media", [number, title])) is not None:
        return failed
    s = store_of(request)
    csid = new_csid()
    approved = _field(body, "approvedForWeb")
    s.media[csid] = Media(csid, identification_number=number, title=title, xml=body.decode(),
                          approved_for_web=approved.lower() != "false")
    return _lost(s, "media") or _created(request, "media", csid)


@app.put("/cspace-services/media/{csid}/blob")
async def attach_file(csid: str, request: Request, file: UploadFile) -> Response:
    """Attach a file to a Media record: makes the Blob record and sets the Media record's blobCsid. A file of
    KEEP_BYTES or less is kept, and served as the original and as every derivative (F10); a larger one isn't, so the
    record then has no file (F11)."""
    if (refused := _gate(request, "media", "U")):
        return refused
    s = store_of(request)
    if (status := s.fail_next.pop("media_blob", None)):
        return Response(status_code=status)
    media = s.media.get(csid)
    if media is None:
        return Response(status_code=404)
    if (failed := _fail(request, "upload", [file.filename or "", *_media_names(s, csid)])) is not None:
        return failed
    size, head = 0, b""
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size <= KEEP_BYTES:
            head += chunk
    blob = new_csid()
    kind = file.content_type or "application/octet-stream"
    s.blobs[blob] = {"name": file.filename, "size": size, "type": kind, "media": csid}
    media.files = {name: (head, kind) for name in ("content", *DERIVATIVES)} if size <= KEEP_BYTES else {}
    media.blob = blob
    media.band = None
    media.updated_at = now()
    return _lost(s, "media_blob") or _created(request, "blobs", blob)


@app.get("/cspace-services/media/{csid}")
def get_media(csid: str, request: Request) -> Response:
    if (refused := _gate(request, "media", "R")):
        return refused
    s = store_of(request)
    media = s.media.get(csid)
    if media is None:
        return Response(status_code=404)
    return _xml(media_xml(s, media))


def _serve(media: Media | None, name: str) -> Response:
    if media is None or name not in media.files:
        return Response(status_code=404)
    content, content_type = media.files[name]
    if content is None:
        # The band's shared file, made different for each record by a comment naming it, so no two records' files
        # are the same bytes (Serena stores files by content hash), without copying the file for each request.
        shared = bands.band_file(bands.band_of(name, media.band or ""))
        head = bands.marked_head(media.csid)
        return StreamingResponse(bands.stream(head, shared), media_type=content_type,
                                 headers={"Content-Length": str(len(head) + len(shared) - 2)})
    return Response(content, media_type=content_type)


@app.get("/cspace-services/media/{csid}/blob/content")
def get_original(csid: str, request: Request) -> Response:
    return _gate(request, "media", "R") or _serve(store_of(request).media.get(csid), "content")


@app.get("/cspace-services/media/{csid}/blob/derivatives/{name}/content")
def get_derivative(csid: str, name: str, request: Request) -> Response:
    return _gate(request, "media", "R") or _serve(store_of(request).media.get(csid), name)


@app.get("/cspace-services/blobs/{csid}")
def get_blob(csid: str, request: Request) -> Response:
    if (refused := _gate(request, "media", "R")):
        return refused
    s = store_of(request)
    known = s.blobs.get(csid)
    if s.media_of_blob(csid) is None and known is None:
        return Response(status_code=404)
    extra = ""
    if known:
        extra = (f"<name>{escape(known.get('name') or '')}</name><length>{known.get('size', 0)}</length>"
                 f"<mimeType>{escape(known.get('type') or '')}</mimeType>")
    return _xml('<document name="blobs"><ns2:blobs_common xmlns:ns2="http://collectionspace.org/services/blob">'
                f"<csid>{csid}</csid>{extra}</ns2:blobs_common></document>")


@app.get("/cspace-services/blobs/{csid}/derivatives/{name}/content")
def get_blob_derivative(csid: str, name: str, request: Request) -> Response:
    """A Blob's derivative. Real CollectionSpace makes resized JPEGs; the simulator serves the file itself."""
    return _gate(request, "media", "R") or _serve(store_of(request).media_of_blob(csid), name)


# --- Objects, relations and groups

@app.get("/cspace-services/relations")
def find_relations(request: Request) -> Response:
    if (refused := _gate(request, "relations", "R")):
        return refused
    q = request.query_params
    # Real CollectionSpace names relation results <relation-list-item>, unlike other lists' <list-item>.
    items = "".join(f"<relation-list-item><csid>{c}</csid></relation-list-item>"
                    for c, r in store_of(request).relations.items()
                    if r["subjectCsid"] == q.get("sbj") and r["objectCsid"] == q.get("obj"))
    return _xml(f'<ns2:relations-common-list xmlns:ns2="http://collectionspace.org/services/relation">{items}'
                "</ns2:relations-common-list>")


@app.post("/cspace-services/relations")
async def create_relation(request: Request) -> Response:
    if (refused := _gate(request, "relations", "C")):
        return refused
    s = store_of(request)
    body = await request.body()
    rel = {k: _field(body, k) for k in ("subjectCsid", "subjectDocumentType", "objectCsid", "objectDocumentType")}
    names = _media_names(s, rel["subjectCsid"]) + _media_names(s, rel["objectCsid"])
    if (failed := _fail(request, "relation", names)) is not None:
        return failed
    csid = new_csid()
    s.relations[csid] = rel
    return _lost(s, "relations") or _created(request, "relations", csid)


@app.get("/cspace-services/collectionobjects/{csid}")
def get_object(csid: str, request: Request) -> Response:
    """An Object record: its number, and for the sample sensitive objects the fields PAHMA's rules read."""
    if (refused := _gate(request, "collectionobjects", "R")):
        return refused
    o = store_of(request).objects.get(csid)
    if not o or o.get("deleted"):
        return Response(status_code=404)
    sens = o.get("sensitivity") or {}
    dept = sens.get("department")
    common = (f"<objectNumber>{escape(o['objectNumber'])}</objectNumber>"
              + (f"<responsibleDepartments><responsibleDepartment>{escape(dept)}</responsibleDepartment>"
                 "</responsibleDepartments>" if dept else ""))
    statuses = "".join(f"<pahmaObjectStatus>{escape(x)}</pahmaObjectStatus>" for x in sens.get("objectStatus", []))
    restrictions = "".join(f"<accessRestrictionGroup><accessRestrictionType>{escape(a['type'])}"
                           f"</accessRestrictionType><accessRestrictionLevel>{escape(a['level'])}"
                           "</accessRestrictionLevel></accessRestrictionGroup>"
                           for a in sens.get("accessRestrictions", []))
    pahma = ((f"<pahmaObjectStatusList>{statuses}</pahmaObjectStatusList>" if statuses else "")
             + (f"<nagpraStatus>{escape(sens['nagpraStatus'])}</nagpraStatus>" if sens.get("nagpraStatus") else "")
             + (f"<accessRestrictionGroupList>{restrictions}</accessRestrictionGroupList>" if restrictions else ""))
    return _xml('<document name="collectionobjects">'
                '<ns2:collectionobjects_common xmlns:ns2="http://collectionspace.org/services/collectionobject">'
                f"{common}</ns2:collectionobjects_common>"
                '<ns2:collectionobjects_pahma '
                'xmlns:ns2="http://collectionspace.org/services/collectionobject/local/pahma">'
                f"{pahma}</ns2:collectionobjects_pahma></document>")


@app.post("/cspace-services/collectionobjects")
async def create_object(request: Request) -> Response:
    if (refused := _gate(request, "collectionobjects", "C")):
        return refused
    s = store_of(request)
    body = await request.body()
    number = _field(body, "objectNumber")
    if (failed := _fail(request, "objectCreate", [number])) is not None:
        return failed
    csid = new_csid()
    s.objects[csid] = {"objectNumber": number, "deleted": False}
    return _lost(s, "collectionobjects") or _created(request, "collectionobjects", csid)


@app.post("/cspace-services/groups")
async def create_group(request: Request) -> Response:
    if (refused := _gate(request, "groups", "C")):
        return refused
    s = store_of(request)
    body = await request.body()
    title = _field(body, "title")
    if (failed := _fail(request, "group", [title])) is not None:
        return failed
    if not title:
        return Response(status_code=400)
    csid = new_csid()
    s.groups[csid] = {"title": title, "deleted": False}
    return _lost(s, "groups") or _created(request, "groups", csid)


@app.get("/cspace-services/{service}")
def authority_vocabularies(service: str, request: Request) -> Response:
    """The vocabularies of an authority. Like PAHMA's server: local Persons and Organizations only (no "shared")."""
    import uuid

    if service not in ("personauthorities", "orgauthorities"):
        return Response(status_code=404)
    if (refused := _gate(request, service, "R")):
        return refused
    short, name = (("person", "Local Persons") if service == "personauthorities"
                   else ("organization", "Local Organizations"))
    item = (f"<list-item><csid>{uuid.uuid5(uuid.NAMESPACE_URL, service)}</csid><shortIdentifier>{short}"
            f"</shortIdentifier><displayName>{name}</displayName></list-item>")
    return _xml(f"{_LIST}{item}</ns2:abstract-common-list>")


# --- middleware: inactive accounts, slowness on demand, and each museum's path prefix

@app.middleware("http")
async def inactive_accounts(request: Request, call_next):  # type: ignore[no-untyped-def]
    """An inactive account (Store.inactive): CollectionSpace answers every request of its with 409."""
    s = store_of(request)
    login = _login(request) if s.inactive else None
    if login and login[0] in s.inactive:
        return Response(status_code=409)
    return await call_next(request)


@app.middleware("http")
async def slow_down(request: Request, call_next):  # type: ignore[no-untyped-def]
    """With /_fake/slow, creates and uploads take a while, so a job runs long enough to watch or cancel."""
    s = store_of(request)
    if s.delay and request.method in ("POST", "PUT") and request.url.path.startswith("/cspace-services/"):
        await asyncio.sleep(s.delay)
    return await call_next(request)


class ThrottleUploads:
    """With /_fake/slow?upload_mbps=N, a file upload's body is read at about N MB/s, so a client's upload progress
    can be watched (it slows reading the request body)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        mbps = stores[museum_of_scope(scope)].upload_mbps if scope["type"] == "http" else 0
        if not mbps or scope["method"] != "PUT" or not scope["path"].endswith("/blob"):
            await self.app(scope, receive, send)
            return

        async def slow_receive() -> Any:
            message = await receive()
            if message["type"] == "http.request" and message.get("body"):
                await asyncio.sleep(len(message["body"]) / (mbps * 1024 * 1024))
            return message
        await self.app(scope, slow_receive, send)


class MuseumPrefix:
    """Lets each museum's CollectionSpace be the simulator under a path, http://<simulator>/<museum>, as well as under
    a host name of its own (an AWS environment has one name for the simulator in its private DNS). The prefix is
    removed here, and museum_of reads it. Paths without a museum's prefix pass unchanged."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            first, _, rest = scope["path"].lstrip("/").partition("/")
            if first in TENANT_IDS and rest:
                scope = {**scope, "fake_museum": first, "path": "/" + rest, "raw_path": ("/" + rest).encode()}
        await self.app(scope, receive, send)


app.include_router(hooks.router)
app.add_middleware(ThrottleUploads)
app.add_middleware(MuseumPrefix)  # added last, so it runs first: everything after it sees the path without prefix
