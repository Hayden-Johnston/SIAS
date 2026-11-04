# Sandbox for the pi coding agent (local Qwen worker). Only the paths the dispatcher mounts are visible;
# no Docker socket, no Maya key, so it cannot touch servers on the rig.
FROM node:22-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends git python3 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
RUN npm install -g @earendil-works/pi-coding-agent@1.5.0
USER node
