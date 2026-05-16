FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for MarkItDown + bw (curl/tar to fetch the
# binary, git because bw shells out to git for its orphan-branch storage).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    curl \
    ca-certificates \
    tar \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install the bw (beadwork) binary. Version pinned to match the
# workspace's local bw 0.13.0 — when bumping, also bump the SHA256
# below to the matching value from
# https://github.com/jallum/beadwork/releases. ariadne--8fd.2 / Phase 2.
ARG BW_VERSION=0.13.0
ARG BW_SHA256=97fa35b38bbefe0a1572956c85dd867eade13d0c1bbed4b5495e08d04778263c
RUN set -eux; \
    curl -fsSL -o /tmp/bw.tar.gz \
      "https://github.com/jallum/beadwork/releases/download/v${BW_VERSION}/beadwork_${BW_VERSION}_linux_amd64.tar.gz"; \
    echo "${BW_SHA256}  /tmp/bw.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/bw.tar.gz -C /tmp; \
    install -m 0755 /tmp/bw /usr/local/bin/bw; \
    rm -rf /tmp/bw.tar.gz /tmp/bw; \
    bw --version

# Install Python dependencies
COPY src/pyproject.toml src/
COPY src/pipeline/ src/pipeline/
RUN pip install --no-cache-dir ./src/

# Copy config and migrations
COPY config/ config/
COPY migrations/ migrations/

# Default port (Railway sets PORT automatically)
ENV PORT=8000

# Phase 5 (ariadne--8fd.9): the bw HTTP surface persists per-slug
# git repos under BW_REPOS_ROOT (default /data/bw-repos). Volume
# binding is operator-configured per-platform:
#   • Railway: dashboard → Service → Settings → Volumes → "Add
#     volume", mount path /data/bw-repos. Railway's docs explicitly
#     ban the Dockerfile VOLUME keyword, so we do NOT declare one
#     here — see https://docs.railway.com/volumes.
#   • Self-hosted Docker: bind-mount or named volume at runtime
#     (-v <host-path>:/data/bw-repos).
# App startup (src/pipeline/api/app.py) ``makedirs`` the path on
# every boot, so a missing-but-creatable mount works on first run;
# a missing-and-uncreatable mount degrades the bw routes only
# (search / documents stay functional).

EXPOSE 8000

CMD ["ariadne-core", "serve"]
