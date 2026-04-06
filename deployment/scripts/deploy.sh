#!/bin/bash
# Deploy latest code to the droplet
# Run on the droplet after git pull
# Usage: bash deployment/scripts/deploy.sh

set -euo pipefail

APP_DIR="/opt/app"

echo "=== Deploying AiCC MCP Server ==="

cd "${APP_DIR}"

# Pull latest code
echo "Pulling latest code..."
git pull origin main

# Rebuild and restart container
echo "Rebuilding container..."
docker compose -f deployment/docker/docker-compose.prod.yml build

echo "Restarting container..."
docker compose -f deployment/docker/docker-compose.prod.yml down
docker compose -f deployment/docker/docker-compose.prod.yml up -d

# Wait for container to be healthy
echo "Waiting for server to start..."
sleep 3

# Health check
echo "Checking health..."
if curl -sf http://127.0.0.1:8443/health > /dev/null 2>&1; then
    echo "Health check passed."
    curl -s http://127.0.0.1:8443/health | python3 -m json.tool
else
    echo "WARNING: Health check failed. Check logs:"
    echo "  docker logs aicc-mcp --tail 50"
fi

echo ""
echo "=== Deploy complete ==="
echo "Logs: docker logs aicc-mcp --tail 50 -f"
