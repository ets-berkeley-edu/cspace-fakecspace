#!/usr/bin/env bash
# Regenerates the hash-pinned requirements files from pyproject.toml and requirements-tools.in. Never edit them by hand.
# Run with Python 3.11 (.python-version) and requirements-tools.txt installed. Extra arguments go to pip-compile,
# e.g. --upgrade or --upgrade-package fastapi.
set -euo pipefail
cd "$(dirname "$0")"

version=$(python -c 'import sys; print("%d.%d" % sys.version_info[:2])')
if [ "$version" != "$(cat .python-version)" ]; then
  echo "This is Python $version. Use Python $(cat .python-version), the version CI runs." >&2
  exit 1
fi

options=(--quiet --generate-hashes --allow-unsafe --strip-extras)
# requirements.txt: the package as a server (uvicorn, and pyvips for size bands), what the Dockerfile installs.
pip-compile "${options[@]}" --all-build-deps --extra server --extra bands "$@" -o requirements.txt pyproject.toml
# requirements-dev.txt: the same versions plus the tools that test and build it (setuptools: builds without isolation).
pip-compile "${options[@]}" --all-build-deps --extra dev -c requirements.txt "$@" -o requirements-dev.txt pyproject.toml
pip-compile "${options[@]}" "$@" -o requirements-tools.txt requirements-tools.in
