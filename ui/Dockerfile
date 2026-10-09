# Image for the read-only database UI and its browser tests. Separate from the pipeline
# image: it holds Flask, Playwright and Chromium, and none of the pipeline's packages.
FROM python:3.11-slim

WORKDIR /workspace

# the checkout is mounted read-only; bytecode caches cannot be written
ENV PYTHONDONTWRITEBYTECODE=1
# Chromium in a shared path, readable by the non-root user below
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

COPY ui/requirements.txt /tmp/ui-requirements.txt
RUN pip install --no-cache-dir -r /tmp/ui-requirements.txt \
    && playwright install --with-deps chromium \
    && useradd --create-home ui

USER ui

CMD ["sleep", "infinity"]
