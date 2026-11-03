ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml ./
COPY --chown=10001:10001 bot ./bot
RUN pip install --index-url ${PIP_INDEX_URL} --timeout 30 . && useradd --uid 10001 --create-home bot
COPY --chown=10001:10001 scripts ./scripts
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "bot"]
