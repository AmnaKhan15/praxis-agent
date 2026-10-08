# Praxis in a container: the same app, the same Python and the same packages on any machine.
#
#   docker build -t praxis .
#   docker run --rm -p 8000:8000 --env-file .env praxis
#
# then open http://localhost:8000

# 1. Start from a small, ready-made Python image.
FROM python:3.12-slim

# Print logs straight away, and do not write .pyc files into the image.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

# 2. Install the packages first. Docker caches this layer, so rebuilds are fast
#    when only the code changes. uvicorn is the server program that runs FastAPI.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt "uvicorn>=0.30"

# 3. Run as a normal user, not root, so a bug in the app cannot touch the whole container.
RUN useradd --create-home --uid 10001 praxis

# 4. Copy the project in (see .dockerignore for what is left out, including any .env file).
COPY --chown=praxis:praxis . .

USER praxis
EXPOSE 8000

# Ask the app if it is alive every 30 seconds (Docker shows "healthy" or "unhealthy").
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT','8000'), timeout=3)"

# Keys are NOT in the image. They are passed in at run time with --env-file or -e.
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
