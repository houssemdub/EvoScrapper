# Multi-stage production Dockerfile for EvoScrapper
# Combines Python 3.12, Node.js 20, and FFmpeg for ultra-low latency streaming

FROM python:3.12-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system dependencies: FFmpeg, curl, Node.js 20, build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    gnupg \
    ca-certificates \
    build-essential \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get purge -y build-essential \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -U pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# Install Node streamer dependencies
COPY streamer/package*.json ./streamer/
RUN cd streamer && npm ci --omit=dev

# Copy application source code
COPY . .

# Ensure storage directories exist
RUN mkdir -p data .stream_cache

# Expose primary API, Web UI, and BitTorrent P2P/DHT ports
EXPOSE 8009 8889 50000/tcp 50000/udp 50001/udp

# Healthcheck probe against /health
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8009/health || exit 1

# Default execution
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8009"]
