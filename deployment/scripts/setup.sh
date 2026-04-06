#!/bin/bash
# One-time server setup for AiCC MCP Server
# Run as root on a fresh Ubuntu 24.04 droplet
# Usage: bash deployment/scripts/setup.sh

set -euo pipefail

echo "=== AiCC MCP Server -- Initial Setup ==="

# Update system
echo "Updating system packages..."
apt-get update && apt-get upgrade -y

# Install Docker
echo "Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
    echo "Docker installed."
else
    echo "Docker already installed."
fi

# Install Docker Compose plugin
echo "Installing Docker Compose..."
if ! docker compose version &> /dev/null; then
    apt-get install -y docker-compose-plugin
    echo "Docker Compose installed."
else
    echo "Docker Compose already installed."
fi

# Install nginx
echo "Installing nginx..."
if ! command -v nginx &> /dev/null; then
    apt-get install -y nginx
    systemctl enable nginx
    echo "nginx installed."
else
    echo "nginx already installed."
fi

# Create application directories
echo "Creating directories..."
mkdir -p /opt/app/data
mkdir -p /opt/app/logs

# Add rate limiting zone to nginx.conf if not already present
if ! grep -q "limit_req_zone.*mcp" /etc/nginx/nginx.conf; then
    echo "Adding rate limit zone to nginx.conf..."
    sed -i '/http {/a \    limit_req_zone $binary_remote_addr zone=mcp:10m rate=30r/m;' /etc/nginx/nginx.conf
fi

# Copy nginx config
echo "Configuring nginx..."
cp /opt/app/deployment/nginx/aicc-mcp.conf /etc/nginx/sites-available/aicc-mcp.conf

# Remove default site if exists
rm -f /etc/nginx/sites-enabled/default

# Enable site
ln -sf /etc/nginx/sites-available/aicc-mcp.conf /etc/nginx/sites-enabled/aicc-mcp.conf

# Create production env file if not exists
if [ ! -f /opt/app/deployment/.env.production ]; then
    echo "Creating .env.production from template..."
    cp /opt/app/deployment/.env.production.example /opt/app/deployment/.env.production
    echo "Edit /opt/app/deployment/.env.production with your settings."
fi

# Initialize the database
echo "Initializing database..."
cd /opt/app
docker compose -f deployment/docker/docker-compose.prod.yml build
docker compose -f deployment/docker/docker-compose.prod.yml up -d

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit /opt/app/deployment/.env.production"
echo "  2. Wait for DNS propagation, then run: bash deployment/scripts/setup-ssl.sh"
echo "  3. Run: bash deployment/scripts/setup-firewall.sh"
echo "  4. Add users: docker exec -it aicc-mcp python -m src.admin.cli add ..."
echo "  5. Verify: curl https://mcp.theintentlayer.com/health"
