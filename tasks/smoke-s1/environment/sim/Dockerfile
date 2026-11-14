FROM docker.io/library/python@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt
RUN useradd --system --uid 10001 envkit \
    && mkdir -p /var/lib/envkit && chown envkit /var/lib/envkit
COPY bundle /opt/envkit
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 ENVKIT_STATE_DIR=/var/lib/envkit
USER envkit
WORKDIR /opt/envkit
EXPOSE 8000
CMD ["python", "-m", "envkit.server"]
