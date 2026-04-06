#!/bin/bash
# Setup SSL certificates via certbot (Let's Encrypt)
# Run after DNS is pointing to the droplet
# Usage: bash deployment/scripts/setup-ssl.sh

set -euo pipefail

DOMAIN="mcp.theintentlayer.com"

echo "=== Setting up SSL for ${DOMAIN} ==="

# Install certbot
if ! command -v certbot &> /dev/null; then
    echo "Installing certbot..."
    apt-get install -y certbot python3-certbot-nginx
fi

# Stop nginx temporarily for standalone verification
# (or use nginx plugin if nginx is already configured)
echo "Obtaining certificate..."
certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos --email nikhil@omspark.com

# Test nginx config
nginx -t

# Reload nginx
systemctl reload nginx

# Verify auto-renewal
echo "Testing certificate auto-renewal..."
certbot renew --dry-run

echo ""
echo "=== SSL setup complete ==="
echo "Certificate installed for ${DOMAIN}"
echo "Auto-renewal is configured via certbot timer."
