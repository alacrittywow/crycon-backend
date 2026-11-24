FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN groupadd --system crycon \
    && useradd --system --gid crycon --home-dir /app crycon

COPY pyproject.toml requirements.txt requirements-dev.txt ./
COPY src ./src
COPY miniapp ./miniapp
COPY *.py ./

RUN python -m pip install --no-cache-dir .

USER crycon

EXPOSE 8000

CMD ["uvicorn", "crycon.api:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS test

USER root

COPY tests ./tests
COPY *.sql ./

RUN python -m pip install --no-cache-dir ".[dev]"

USER crycon

CMD ["python", "-m", "pytest", "-q"]
