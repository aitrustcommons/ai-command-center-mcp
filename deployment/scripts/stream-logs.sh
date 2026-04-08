#!/bin/bash
# Stream logs from the MCP server to the local terminal
# Usage (from local machine):
#   ssh root@<droplet-ip> bash /opt/mcp/deployment/scripts/stream-logs.sh
# Or run directly on the droplet:
#   bash deployment/scripts/stream-logs.sh

set -euo pipefail

echo "=== Streaming AiCC MCP Server logs ==="
echo "Press Ctrl+C to stop"
echo ""

docker logs aicc-mcp --tail 100 -f
