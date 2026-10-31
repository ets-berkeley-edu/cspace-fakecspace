# fakecspace

A small simulated [CollectionSpace](https://collectionspace.org/) services API, for developing and testing UC
Berkeley's CollectionSpace apps: the Bulk Media Uploader
([cspace-bulk-media-uploader](https://github.com/ets-berkeley-edu/cspace-bulk-media-uploader)) and Serena, the media
server ([cspace-media-server](https://github.com/ets-berkeley-edu/cspace-media-server)). Both apps use this one copy
of the simulator.

> **It is not CollectionSpace, and it must never hold real data.** Its accounts are synthetic and each password is
> the user name (published here, in `src/fakecspace/accounts.py`). Its records are in memory and gone when it stops.
> Behaviour against the real server must be confirmed on a CollectionSpace test tenant. Each app's deployment keeps
> its own switch, so the simulator is never deployed with production.

## What it simulates

- **One CollectionSpace per museum** (bampfa, botgarden, cinefiles, pahma, ucjeps), each with its own records. The
  museum comes from the host name a request uses (`pahma.fakecspace`) or a path prefix (`/pahma/cspace-services/...`);
  PAHMA when neither names one. Tenant IDs are synthetic (PAHMA is 14).
- **Accounts**: `accounts/0/accountperms` and `accounts/0/accountroles`, with the BMU's users (`admin`, `limited`,
  `intern`, `newstaff`, `reader`, `bmureader`) and Serena's (`serena`, `pahma-admin`, `viewer`; `admin` is a Serena
  admin of every museum).
- **Records**: Media (GET, POST, search by `identificationNumber`, `title` or `blobCsid`), files attached with
  `PUT media/<csid>/blob`, Objects, Relations, groups, Person and Organization terms, the languages vocabulary, and
  the date parser.
- **Files**: `media/<csid>/blob/content`, `media/<csid>/blob/derivatives/<name>/content`, `blobs/<csid>` and
  `blobs/<csid>/derivatives/<name>/content`. A file uploaded the BMU's way is served as the original and as every
  derivative (Thumbnail, Small, Medium, FullHD, OriginalJpeg). A file over 5 MB isn't kept: the record then has no
  file.
- **Development hooks** under `/_fake` (`src/fakecspace/hooks.py` lists them): reset, sample sets, records with
  sample files, soft delete, replace, an outage, failures on demand, slowness, and terms changed meanwhile.

The simulator starts empty. A client asks for the samples it needs after each reset:

```bash
curl -X POST http://localhost:8180/_fake/reset
curl -X POST http://localhost:8180/_fake/seed -H 'Content-Type: application/json' -d '{"set": "bmu"}'
```

### Failures on demand

`POST /_fake/fail` takes one JSON shape for both apps:

| Field | Meaning |
| --- | --- |
| `step` | One step of the BMU's work: `media`, `upload`, `objectSearch`, `objectCreate`, `relation`, `mediaSearch`, `group`, `termRead`. Without a step, the rule applies to every request whose path contains `path`. |
| `path` | Part of a request's path, e.g. `/blob/content`. |
| `match` | With a step: part of a name the step carries (identification number, file name, object number, group title, term). |
| `status` | The HTTP status answered (default 500). |
| `effect` | `none` or `many`, for `objectSearch` and `mediaSearch`: what the search finds, instead of a status. |
| `times` | How many requests fail (default 1; 0 until `DELETE /_fake/fail`). |
| `agent` | Only requests whose User-Agent starts with this, e.g. `bmu-worker` for the BMU's job runs. |

```bash
curl -X POST http://localhost:8180/_fake/fail -H 'Content-Type: application/json' \
  -d '{"path": "/blob/content", "status": 503, "times": 2}'
```

## Using it from an app

Pin a version from PyPI, with its hash, in the app's development requirements (`pip install fakecspace` for a quick
try). The extras: `server` (uvicorn, to run it) and `bands` (pyvips, for records with a size band).

In tests, call it in-process, with no server:

```python
from fastapi.testclient import TestClient
from fakecspace.app import app, stores

stores.reset()                       # every museum's store empty
client = TestClient(app, base_url="http://pahma.fakecspace")
stores["pahma"].add("m-1")           # a Media record with sample files
```

`fakecspace.app.store` is PAHMA's store. A Media record (`store.media[csid]`) can be read by attribute
(`media.blob`) or by CollectionSpace's field name (`media["blobCsid"]`).

To run it: `uvicorn fakecspace.app:app --port 8180`, or
`docker build -t fakecspace . && docker run --rm -p 8180:8180 fakecspace`.

## Shared mode

Each app normally runs its own simulator. To see a file the BMU uploads come out of Serena, both can use one:
`./serena up shared` and `./bmu up shared` each start `compose.shared.yml` from a clone of this repository beside
theirs (or `FAKECSPACE_DIR`), unless it is already running. It joins the Docker network `fakecspace-shared`, where each
museum has its host name (`pahma.fakecspace:8180`), and is published at http://localhost:8680. It runs this clone's
checkout, so check out the tag the apps pin when that matters. It is for local use only.

```bash
docker compose -f compose.shared.yml -p fakecspace-shared up -d --build --wait   # what the apps run
docker compose -f compose.shared.yml -p fakecspace-shared down                   # stop it (both apps lose it)
```

## Development

Python 3.11 (`.python-version`).

```bash
python3.11 -m venv .venv && . .venv/bin/activate
pip install --require-hashes -r requirements-dev.txt
pip install --no-deps --no-build-isolation -e .
pytest -q && ruff check . && mypy
```

Dependencies are listed in `pyproject.toml` and pinned with hashes in `requirements.txt` (the server, what the
Dockerfile installs), `requirements-dev.txt` and `requirements-tools.txt`, all made by `./pin-requirements.sh`.
Never edit those files by hand. `CLAUDE.md` has the rules for changes.

## Releasing

1. In a pull request, set the new version in `src/fakecspace/__init__.py` and add it to `CHANGELOG.md`.
2. Optional dry run: Actions › **Publish** › **Run workflow** on the branch publishes it to TestPyPI.
3. After the merge, tag the merge commit `vX.Y.Z` and push the tag. The **Publish** workflow builds it and, once a
   reviewer approves the `pypi` environment, publishes it to PyPI through trusted publishing (no stored token).
4. Dependabot then proposes the new version in each app.

## License

Copyright The Regents of the University of California: educational, research and not-for-profit use. See `LICENSE`.
