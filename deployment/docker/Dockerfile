FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ src/

# Create data and log directories
RUN mkdir -p /app/data /app/logs

EXPOSE 8443

CMD ["python", "-m", "src.server"]
