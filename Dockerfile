# Production Docker Container for NautilusTrader BTC Options Trading
FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy codebase
COPY . .

# Set Python path
ENV PYTHONPATH=/app

# Expose web dashboard port
EXPOSE 3000

# Default entrypoint: Run the web server or trading node
CMD ["python", "server.py"]
