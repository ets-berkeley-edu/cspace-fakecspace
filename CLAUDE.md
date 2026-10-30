# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`fakecspace`: a simulated CollectionSpace services API, published to PyPI, that the Bulk Media Uploader
(`ets-berkeley-edu/cspace-bulk-media-uploader`) and Serena (`ets-berkeley-edu/cspace-media-server`) install for their
tests, their local stacks and their simulator-only AWS environments. `README.md` says what it simulates and how to
use it.

## Rules that are not negotiable

- **It never holds real data, and it is never CollectionSpace.** Accounts are synthetic, each password is the user
  name. Don't add a way to load real records, proxy to a real server, or persist state to disk beyond a temporary
  folder.
- **Never put a login, token or key in the repository, a test or a chat**, and never read `.env` files. This is a
  public repository: every commit is published.
- **Both apps depend on it.** A change to an endpoint's shape or a hook is a change to both apps: say in the pull
  request which app code or tests must change, and bump the version (minor for anything an app must adapt to).
  Prefer adding to changing.
- **One store per museum** (`context.stores`); a request's museum comes from its host name or path prefix
  (`context.museum_of`), never from a setting. Every new endpoint or hook acts on `store_of(request)`, except
  `/_fake/reset`.
- **Never commit to `main`.** Work on a feature branch and open a pull request. Before committing to a branch,
  `git fetch` and check whether it was already pushed or merged; never amend or rebase a pushed branch.
- The repository owner runs `git push`, `gh pr create`, tags and releases himself: give him the exact commands.

## Commands

```bash
pip install --require-hashes -r requirements-dev.txt && pip install --no-deps --no-build-isolation -e .
pytest -q                          # all tests (a few seconds)
pytest -q tests/test_failures.py   # one file
ruff check . && mypy
./pin-requirements.sh              # after changing a dependency in pyproject.toml (Python 3.11, requirements-tools.txt)
uvicorn fakecspace.app:app --port 8180
```

While working, run only the test files a change affects; run the full suite, ruff and mypy once before each commit.

CI (`.github/workflows/ci.yml`): ruff, mypy, pytest and a wheel build; `dependencies` checks the requirements files
are in step and runs pip-audit. `security.yml` runs gitleaks over the whole history on every pull request and push:
never add a path filter to it. A gitleaks match that isn't a secret goes in `.gitleaksignore`, by fingerprint, with a
reason. `publish.yml` publishes (README: Releasing); its file name and environments (`testpypi`, `pypi`) are named in
the trusted publishers on PyPI and TestPyPI, so don't rename them. Actions are pinned by commit SHA with the version
in a comment; Dependabot moves both.

## Layout (`src/fakecspace/`)

- `app.py`: the CollectionSpace endpoints and the middleware (museum path prefix, inactive accounts, slowness).
- `hooks.py`: the `/_fake` development hooks, and `FailRule`, the one shape of `/_fake/fail`.
- `context.py`: `stores` (one `Store` per museum), `store` (PAHMA's), `museum_of`, `store_of`.
- `store.py`: `Store`, `Media` (attribute and field-name access), `Rule` (failures on demand), tenant IDs.
- `accounts.py`: users, permissions, roles (`ROLE_<tenant id>_<name>`).
- `seeds.py`: sample sets for `/_fake/seed`. `vocab.py`: terms, languages, the date parser.
- `samples.py`, `bands.py`: generated sample files; files of a real one's size for a size band (pyvips).

## Writing

Plain, short sentences. Put "only" directly before the word or phrase it limits ("is needed only for AWS"); the same
care with "just", "even" and "also".
