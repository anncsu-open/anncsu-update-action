FROM debian:bookworm-slim

LABEL org.opencontainers.image.source="https://github.com/luipir/anncsu-update-action"
LABEL org.opencontainers.image.description="Anncsu Update Action - GitHub Action to update Anncsu database from geodiff reports"
LABEL org.opencontainers.image.authors="luipir"

# Install git for git history mode and all necessary packages for Python and uv
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates=20230311+deb12u1 \
        curl=7.88.1-10+deb12u15 \
        git=1:2.39.5-0+deb12u2 \
        python3=3.11.2-1+b1 \
        python3-venv=3.11.2-1+b1 \
        python3-pip=23.0.1+dfsg-1 && \
        apt-get clean && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --break-system-packages uv==0.9.18

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1
# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy
# Ensure installed tools can be executed out of the box
ENV UV_TOOL_BIN_DIR=/usr/local/bin

COPY pyproject.toml uv.lock /
RUN uv sync --locked --no-dev

COPY src /src
ENV PATH="/.venv/bin:$PATH"
ENTRYPOINT ["python", "/src/main_with_cli.py"]
