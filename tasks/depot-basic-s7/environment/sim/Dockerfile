FROM python:3.12-slim-bookworm
RUN pip install --no-cache-dir mcp==2.3.0 uvicorn==0.54.0
RUN useradd --system --uid 10001 envkit \
    && mkdir -p /var/lib/envkit && chown envkit /var/lib/envkit
COPY bundle /opt/envkit
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 ENVKIT_STATE_DIR=/var/lib/envkit
USER envkit
WORKDIR /opt/envkit
EXPOSE 8000
CMD ["python", "-m", "envkit.server"]
