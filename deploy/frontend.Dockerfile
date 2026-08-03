# Builds the React SPA into static files. The output is copied into a small
# volume that Caddy serves directly — no Node process runs in production, the
# app is just static assets behind the same origin as the API.
#
# Build context is the repo root (see deploy/docker-compose.server.yml), so
# paths here are relative to that.

FROM node:22-alpine AS builder
WORKDIR /build

# Install deps first for layer caching.
COPY frontend/app/package.json frontend/app/package-lock.json ./
RUN npm ci

# Build. VITE_API_BASE_URL is baked in at build time; in the single-origin
# Caddy deployment the API is same-origin under /api/v1, so that's the default.
COPY frontend/app/ ./
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build

# The runtime "image" is just the built assets on a tiny base; the compose
# stack mounts these into a volume Caddy reads. Using busybox keeps it minimal.
FROM busybox:1.36
WORKDIR /dist
COPY --from=builder /build/dist/ ./
# A no-op long-running command so the container stays up long enough for the
# volume copy in the entrypoint; in practice compose copies via a shared volume.
CMD ["sh", "-c", "cp -r /dist/. /srv/frontend/ && echo 'frontend assets published' && sleep infinity"]
