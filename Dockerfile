# 默认 bookworm（Debian 12，apt 更稳）。若 Docker 镜像站对 bookworm 限流 429，可改用本机已缓存的 slim：
#   docker compose build --build-arg PYTHON_BASE=python:3.11-slim --build-arg APT_USE_MIRROR=1
# 或在 .env 设置 PYTHON_BASE / APT_USE_MIRROR
ARG PYTHON_BASE=python:3.11-slim-bookworm
FROM ${PYTHON_BASE}

WORKDIR /app

# 降低 deb.debian.org 偶发 502 / 中断
RUN printf 'Acquire::Retries "5";\n' > /etc/apt/apt.conf.d/80-retries

# 若构建时 apt 仍失败，可在 .env 设 APT_USE_MIRROR=1 或：
#   docker compose build --build-arg APT_USE_MIRROR=1
ARG APT_USE_MIRROR=0
RUN if [ "$APT_USE_MIRROR" = "1" ]; then \
      for f in /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list.d/*.sources /etc/apt/sources.list.d/*.list; do \
        [ -f "$f" ] || continue; \
        sed -i 's/deb.debian.org/mirrors.aliyun.com/g' "$f"; \
        sed -i 's/security.debian.org/mirrors.aliyun.com/g' "$f"; \
      done; \
    fi

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# 镜像内 pip 常为 24.x；叠加 Docker 复用旧 install 层时，易与当前 PyPI wheel 校验不一致。
# 先升级 pip；本地重建请用 scripts/local_rebuild_docker.sh（含 build --no-cache）或手动 docker compose build --no-cache。
RUN python -m pip install --upgrade "pip>=25" setuptools wheel \
    && python -m pip --version \
    && python -m pip install --no-cache-dir -r requirements.txt

RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser \
    && mkdir -p /app/logs && chown -R appuser:appuser /app

COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 5000 8501
