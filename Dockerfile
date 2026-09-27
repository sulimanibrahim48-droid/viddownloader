FROM python:3.11-slim

# Install system dependencies (FFmpeg is required for stitching videos)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY webapp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy web application files
COPY webapp/ .

ENV PORT=8000
EXPOSE 8000

# Start FastAPI application
CMD ["python", "app.py"]
