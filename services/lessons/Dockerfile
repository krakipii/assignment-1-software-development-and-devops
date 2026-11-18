# Image of the lessons service. Build it from this folder:
#     docker build -t lessons --build-arg GIT_SHA=$(git rev-parse HEAD) .
# Python version pinned to the one the tests run with.
FROM python:3.12.9-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# The service runs as this user, which has no root rights.
RUN useradd --create-home --uid 10001 app
WORKDIR /app

# Dependencies first: Docker reuses this layer as long as requirements.txt is unchanged.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Only the files the service needs: no tests, no .env, no secrets.
COPY app.py auth.py customers_client.py db.py migrate.py routes.py service.py ./
COPY migrations ./migrations

# The commit the image was built from, shown by /health. Set by the pipeline.
ARG GIT_SHA=dev
ENV GIT_SHA=$GIT_SHA

USER app
EXPOSE 8000

# gunicorn instead of Flask's development server. --preload runs create_app(),
# and so the migrations, once before the worker starts; one worker with four
# threads, so migrations never run twice at the same time in one container.
# --timeout 120 leaves room for a paused Azure database to resume.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --preload --workers 1 --threads 4 --timeout 120 'app:create_app()'"]
