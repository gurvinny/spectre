# SPECTRE sensor image
# Author: gurvinny
FROM python:3.11-slim

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

CMD ["python", "-m", "spectre.main"]
