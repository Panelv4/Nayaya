# NYAYA-RAC v0.5.0 — citizen reporting portal + rules-as-code library.
# Standard library only; the image is a bare Python interpreter plus this tree.
#
#   docker build -t nyaya-rac .
#   docker run --rm -p 8000:8000 \
#     -e NYAYA_ADMIN_PASSWORD='choose-a-strong-password-12plus' \
#     -v nyaya-data:/data nyaya-rac
#
# WARNING: the portal holds personal data and has no TLS. Run it on loopback
# or behind a TLS-terminating proxy; never expose it directly to the internet.
FROM python:3.12-slim

WORKDIR /app
COPY . /app

# Data lives outside the image layer so it survives rebuilds.
ENV NYAYA_DB=/data/nyaya-rac.sqlite3 \
    NYAYA_AUDIT_DB=/data/nyaya-rac-audit.sqlite3 \
    NYAYA_EVIDENCE_DIR=/data/evidence \
    NYAYA_HOST=0.0.0.0 \
    NYAYA_PORT=8000 \
    NYAYA_ALLOW_PUBLIC_BIND=1 \
    PYTHONUNBUFFERED=1

RUN mkdir -p /data/evidence && \
    python -m compileall -q server.py engine.py db.py legal_kb.py digilocker.py seed.py smoke.py tests.py nyayacode && \
    python -m nyayacode check

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).status==200 else 1)"

CMD ["python", "server.py"]
