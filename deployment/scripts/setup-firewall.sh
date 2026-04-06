#!/bin/bash
# Setup UFW firewall and fail2ban
# Usage: bash deployment/scripts/setup-firewall.sh

set -euo pipefail

echo "=== Setting up firewall ==="

# Install fail2ban
if ! command -v fail2ban-client &> /dev/null; then
    echo "Installing fail2ban..."
    apt-get install -y fail2ban
    systemctl enable fail2ban
    systemctl start fail2ban
fi

# Configure UFW
echo "Configuring UFW..."
ufw default deny incoming
ufw default allow outgoing

# Allow SSH
ufw allow ssh

# Allow HTTP and HTTPS
ufw allow 80/tcp
ufw allow 443/tcp

# Enable UFW (non-interactive)
echo "y" | ufw enable

echo "UFW status:"
ufw status verbose

echo ""
echo "=== Firewall setup complete ==="
echo "Allowed: SSH (22), HTTP (80), HTTPS (443)"
echo "All other incoming traffic is blocked."
echo "fail2ban is running for SSH brute-force protection."
