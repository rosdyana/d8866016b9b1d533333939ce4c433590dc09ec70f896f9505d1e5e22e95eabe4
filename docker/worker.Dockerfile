FROM python:3.11-slim

WORKDIR /srv

# xvfb is load-bearing, not convenience: both browser stages run on a
# virtual display rather than true headless, because headless mode is
# trivially detectable and is the single biggest avoidable tell.
#
# chromium is Stage 3's browser - SeleniumBase's CDP mode launches a real
# Chrome/Chromium binary it finds on PATH (see its cdp_driver/config.py,
# which searches for "chromium"/"chromium-browser"). Stage 2 does NOT need
# a browser installed here: Camoufox ships its own patched Firefox, fetched
# below. Nothing in this image uses Playwright's bundled browsers, so they
# are deliberately not downloaded - only the shared libraries both engines
# link against.
RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb \
        chromium \
        libgtk-3-0 libx11-xcb1 libxcb1 libxcomposite1 libxcursor1 libxdamage1 \
        libxext6 libxfixes3 libxi6 libxrandr2 libxrender1 libxtst6 \
        libasound2 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdbus-1-3 \
        libdrm2 libgbm1 libnspr4 libnss3 libpango-1.0-0 libpangocairo-1.0-0 \
        libxkbcommon0 libxss1 libdbus-glib-1-2 fonts-liberation ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
COPY worker ./worker
COPY pipeline ./pipeline
COPY extract ./extract
COPY common ./common

RUN pip install --no-cache-dir ".[worker]"

# Fetch Camoufox's Firefox build (plus its GeoIP database and addons) at
# build time. Left to runtime, every worker would race to download the
# same ~200MB on its first job.
RUN python -m camoufox fetch

CMD ["arq", "worker.main.WorkerSettings"]
