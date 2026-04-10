FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for MarkItDown
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY src/pyproject.toml src/
COPY src/pipeline/ src/pipeline/
RUN pip install --no-cache-dir ./src/

# Copy config and migrations
COPY config/ config/
COPY migrations/ migrations/

# Default port (Railway sets PORT automatically)
ENV PORT=8000

EXPOSE 8000

CMD ["ariadne-core", "serve"]
