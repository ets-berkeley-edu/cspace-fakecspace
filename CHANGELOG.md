# Changelog

## 0.2.0

What Serena's "Make one from the simulator" (Manual refresh) and its fake ETL need, from Serena's own simulator
(cspace-media-server PR #146) before it moves to this package.

- A Media record has a `kind` (image, card, pdf, 3D, audio, video) and an `access` (public, restricted), as a servable
  list gives them. `GET /_fake/media` lists both.
- `POST /_fake/media` takes `"access"` (default public) and `"museum"`: the store to add the record to, whatever the
  request's host name, so a client that calls one address can add records for each museum.
- A file uploaded with `PUT media/<csid>/blob` sets the record's kind from its type (application/pdf: pdf; audio/*,
  video/*, model/*: audio, video, 3D; anything else: image).

## 0.1.0

The first release: the BMU's and Serena's simulators merged into one package.

- Every CollectionSpace endpoint and `/_fake` hook of both simulators.
- One store per museum, told apart by host name or path prefix; `/_fake/reset` empties them all.
- Starts empty; `POST /_fake/seed {"set": "bmu"}` adds the BMU's samples.
- PAHMA's tenant ID is 14 (Serena's). `admin` has both apps' roles.
- One shape for `POST /_fake/fail` (JSON: `step`, `path`, `match`, `status`, `effect`, `times`, `agent`), replacing
  the BMU's query parameters and Serena's `{match, status, times}`.
- A file uploaded with `PUT media/<csid>/blob` (5 MB or less) is served as the original and as every derivative, at
  `media/<csid>/blob/...` and `blobs/<csid>/derivatives/...`.
- `GET /_fake/media` lists a museum's Media records, for a mock ETL's servable list.
- `Store.requests` records `{user, path}` of every signed-in request (the BMU's `calls`); `Store.calls` is the paths
  of record and file requests (Serena's).
