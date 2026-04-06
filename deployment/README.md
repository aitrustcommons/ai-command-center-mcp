# Deployment Guide

## Architecture

```
Internet (HTTPS :443)
    |
nginx (host-level, SSL via certbot, rate limiting, security headers)
    |
    +-- /*         --> MCP server container (FastAPI, port 8443)
    +-- /health    --> MCP server container (no rate limit)
```

Domain: `mcp.theintentlayer.com`

## Prerequisites

- Ubuntu 24.04 droplet (Digital Ocean, $6/mo basic)
- SSH access as root
- DNS A record: `mcp.theintentlayer.com` pointing to droplet IP

## First-Time Setup

```bash
# 1. SSH into the droplet
ssh root@<droplet-ip>

# 2. Clone the repo
git clone https://github.com/aitrustcommons/ai-command-center-mcp.git /opt/app
cd /opt/app

# 3. Run setup (installs Docker, nginx, creates directories)
bash deployment/scripts/setup.sh

# 4. Configure production environment
nano deployment/.env.production

# 5. Wait for DNS propagation, then setup SSL
bash deployment/scripts/setup-ssl.sh

# 6. Setup firewall
bash deployment/scripts/setup-firewall.sh

# 7. Initialize database and add users
docker exec -it aicc-mcp python -m src.admin.cli init
docker exec -it aicc-mcp python -m src.admin.cli add \
  --name "Nikhil" --email "nikhil@omspark.com" \
  --github-owner nikhilsi --github-repo ns-2026-the-big-push \
  --github-pat "ghp_xxxx" \
  --az-org nikhilsinghal --az-project "The Big Push" --az-pat "xxxx"

# 8. Verify
curl https://mcp.theintentlayer.com/health
```

## Recurring Deployments

```bash
ssh root@<droplet-ip>
bash /opt/app/deployment/scripts/deploy.sh
```

## Rollback

```bash
ssh root@<droplet-ip>
cd /opt/app
git log --oneline -10
git checkout <commit-hash>
bash /opt/app/deployment/scripts/deploy.sh
```

## Logs

```bash
# Stream logs
docker logs aicc-mcp --tail 100 -f

# Or from local machine
ssh root@<droplet-ip> bash /opt/app/deployment/scripts/stream-logs.sh
```

## User Management

All commands run inside the container:

```bash
docker exec -it aicc-mcp python -m src.admin.cli list
docker exec -it aicc-mcp python -m src.admin.cli disable --key aicc-xxx
docker exec -it aicc-mcp python -m src.admin.cli enable --key aicc-xxx
docker exec -it aicc-mcp python -m src.admin.cli rotate --email user@example.com
docker exec -it aicc-mcp python -m src.admin.cli remove --key aicc-xxx
```
