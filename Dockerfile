# The simulator on its own, for a quick local run (each app builds its own simulator image from the pinned package,
# F4):
#   docker build -t fakecspace . && docker run --rm -p 8180:8180 fakecspace
# It isn't CollectionSpace: its accounts' passwords are public (src/fakecspace/accounts.py) and its data is in memory.
# Never run it where real data is.
FROM public.ecr.aws/docker/library/python:3.11-slim-trixie@sha256:db20d8506e2f15b6db39b40b6015ca46bae855dec6dd326d462cfe79ae972893
# eMudhra CA compromise (Oct 2026): take Debian's fixed ca-certificates even if the base image predates it; the build
# fails if the installed version is older than the fix.
RUN apt-get update && apt-get install -y --no-install-recommends --only-upgrade ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' ca-certificates)" ge 20250419+deb13u1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
# Only the pinned versions, checked against their hashes.
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps --no-build-isolation . && rm -rf /app/src \
    && useradd -r -u 10001 fakecspace
USER fakecspace
EXPOSE 8180
CMD ["uvicorn", "fakecspace.app:app", "--host", "0.0.0.0", "--port", "8180", "--no-server-header"]
