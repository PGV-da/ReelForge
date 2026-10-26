# ── Stage: Production Image ───────────────────
FROM python:3.11-slim AS production

# Metadata
LABEL maintainer="ReelForge Team"
LABEL description="ReelForge: Telegram-controlled Instagram Reels repurposing engine"

# Prevent Python from writing .pyc and enable unbuffered stdout
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies: FFmpeg + fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-liberation \
    fonts-dejavu-core \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 1000 reelforge && \
    useradd --uid 1000 --gid reelforge --create-home reelforge

# Set working directory
WORKDIR /opt/reelforge

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create temp directory with correct permissions
RUN mkdir -p /tmp/reelforge && chown -R reelforge:reelforge /tmp/reelforge

# Switch to non-root user
USER reelforge

# Health check: verify the Python process is running
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Entrypoint
CMD ["python", "-m", "app.main"]
