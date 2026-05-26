FROM python:3.14-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY pyproject.toml ./
COPY main.py ./
COPY src ./src
COPY config ./config
COPY eval ./eval

RUN useradd --create-home --shell /bin/bash app \
 && mkdir -p /app/cache /app/output /app/cv /app/jobs \
 && chown -R app:app /app
USER app

ENV PYTHONPATH=/app

ENTRYPOINT ["python", "main.py"]
CMD ["--help"]
