# SPECTRE sensor image
# Author: gurvinny
FROM python:3.14-slim

# Unbuffered logs; no .pyc clutter.
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install deps first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application package.
COPY spectre ./spectre

# Non-root runtime user; the `dialout` group (added in compose via group_add)
# grants access to the /dev/ttyUSB* serial devices.
RUN useradd --create-home --uid 10001 spectre \
    && mkdir -p /data && chown spectre:spectre /data
# A fresh named volume mounted at /data inherits this ownership on first use.
VOLUME ["/data"]
USER spectre

EXPOSE 8100

# Mirrors the compose healthcheck so the image is self-describing when run
# without compose.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8100/health',timeout=3).status==200 else sys.exit(1)"

CMD ["python", "-m", "spectre.main"]
