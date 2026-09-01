FROM python:3.11-slim

WORKDIR /srv

# Three browser engines live in this image, installed three different ways:
#
#   Stage 2 crawl4ai      Playwright's bundled Chromium  (playwright install)
#   Stage 3 Camoufox      its own patched Firefox        (camoufox fetch)
#   Stage 4 SeleniumBase  the apt chromium on PATH       (apt, below)
#
# SeleniumBase's CDP mode launches whatever Chrome/Chromium binary it finds
# on PATH (see its cdp_driver/config.py, which searches for
# "chromium"/"chromium-browser"), which is why the apt package stays even
# though Playwright now downloads a Chromium of its own.
#
# xvfb is load-bearing, not convenience: Stage 4 runs on a virtual display
# rather than true headless, because headless Chromium is trivially
# detectable. Stages 2 and 3 are headless on purpose - see STAGE3_USE_XVFB
# in env.example for the measurement behind Camoufox's.
#
# The library list below is what all three engines link against.
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

# Out of root's home, so adding a `user:` to the compose service later
# doesn't silently lose the browser.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

# Stage 2's Chromium. `--with-deps` installs any system libraries the
# hand-listed set above misses; it is additive, not a replacement, because
# Camoufox's Firefox and the apt chromium still need their own. It runs its
# own `apt-get update`, which repopulates the lists the block above
# deleted - clean them again in the same layer.
RUN python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# crawl4ai appends ".crawl4ai" itself and does the mkdir at *import* time
# (its async_database, module scope), falling back to $HOME. That makes it
# a requirement of `extract/converter.py`, not just of Stage 2, so it has
# to be in the process environment before python starts - .env is too late.
# Note the spelling: it reads CRAWL4_AI_*, not CRAWL4AI_*.
ENV CRAWL4_AI_BASE_DIRECTORY=/var/lib/ccscraper
RUN mkdir -p /var/lib/ccscraper/.crawl4ai

# Stage 3's Firefox build (plus its GeoIP database and addons), at build
# time. Left to runtime, every worker would race to download the same
# ~200MB on its first job.
RUN python -m camoufox fetch

CMD ["arq", "worker.main.WorkerSettings"]
