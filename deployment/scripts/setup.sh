#!/bin/bash
# One-time server setup for AiCC platform (website + MCP server)
# Run as root on a fresh Ubuntu 24.04 droplet
#
# Usage: bash /opt/mcp/deployment/scripts/setup.sh
#
# This sets up the shared infrastructure for both the website and MCP server.
# After running this, clone both repos and run the deploy script.

set -euo pipefail

echo "=== AiCC Platform -- Initial Setup ==="

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

# Create shared directories
echo "Creating directories..."
mkdir -p /opt/data   # shared SQLite DB (both containers mount this)
mkdir -p /opt/logs   # MCP server logs

# Add rate limiting zone to nginx.conf if not already present
if ! grep -q "limit_req_zone.*mcp" /etc/nginx/nginx.conf; then
    echo "Adding rate limit zone to nginx.conf..."
    sed -i '/http {/a \    limit_req_zone $binary_remote_addr zone=mcp:10m rate=30r/m;' /etc/nginx/nginx.conf
fi

# Remove default nginx site
rm -f /etc/nginx/sites-enabled/default

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Clone repos:"
echo "     git clone https://github.com/TheIntentLayer/theintentlayer.com.git /opt/web"
echo "     git clone https://github.com/TheIntentLayer/ai-command-center-mcp.git /opt/mcp"
echo ""
echo "  2. Create env files:"
echo "     cp /opt/web/.env.example /opt/web/.env  # edit secrets"
echo "     cp /opt/mcp/.env.example /opt/mcp/.env  # edit secrets"
echo "     (JWT_SECRET / AICC_JWT_SECRET must match between both files)"
echo ""
echo "  3. Install nginx config:"
echo "     cp /opt/web/deployment/nginx/theintentlayer.conf /etc/nginx/sites-available/aicc"
echo "     ln -sf /etc/nginx/sites-available/aicc /etc/nginx/sites-enabled/aicc"
echo "     nginx -t && systemctl reload nginx"
echo ""
echo "  4. Setup SSL (after DNS propagation):"
echo "     bash /opt/mcp/deployment/scripts/setup-ssl.sh"
echo ""
echo "  5. Setup firewall:"
echo "     bash /opt/mcp/deployment/scripts/setup-firewall.sh"
echo ""
echo "  6. Deploy:"
echo "     bash /opt/web/deployment/scripts/deploy.sh all"
echo ""
echo "  7. Add users:"
echo "     docker exec -it aicc-mcp python -m src.admin.cli add ..."
echo ""
echo "  8. Verify:"
echo "     curl https://mcp.theintentlayer.com/health"
echo "     curl https://theintentlayer.com/"
