#!/bin/bash
# Deploy MCP server to production
#
# This is a convenience wrapper. The canonical deploy infrastructure lives
# in the web repo (theintentlayer.com). This script SSHes to the droplet
# and runs the canonical deploy script for the MCP service only.
#
# Usage (from local machine):
#   bash deployment/scripts/deploy.sh
#
# What it does:
#   1. Checks for uncommitted changes (refuses to deploy dirty state)
#   2. SSHes to the droplet
#   3. Runs the canonical deploy: /opt/web/deployment/scripts/deploy.sh mcp

set -euo pipefail

DROPLET="root@64.23.155.158"

echo "=== Deploy MCP Server ==="

# Safety: refuse to deploy with uncommitted changes
if [[ -n "$(git status --porcelain)" ]]; then
    echo "ERROR: Uncommitted local changes. Commit and push first."
    echo ""
    git status --short
    exit 1
fi

# Show what we're deploying
echo "Local HEAD: $(git log --oneline -1)"
echo "Deploying to: ${DROPLET}"
echo ""

# Run the canonical deploy script on the droplet
ssh "${DROPLET}" "bash /opt/web/deployment/scripts/deploy.sh mcp"
