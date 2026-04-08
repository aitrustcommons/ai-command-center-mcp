# Deployment Guide

## Production Architecture

```
DO Droplet: 64.23.155.158
 |
nginx (SSL via certbot, rate limiting, SSE support)
 |
 +-- theintentlayer.com      --> aicc-web container (port 8080)
 +-- mcp.theintentlayer.com  --> aicc-mcp container (port 8443)

Filesystem:
  /opt/web   -- theintentlayer.com repo (website + OAuth provider)
  /opt/mcp   -- ai-command-center-mcp repo (MCP server)
  /opt/data  -- shared SQLite DB (aicc.db, bind-mounted into both containers)
  /opt/logs  -- MCP server logs
```

Both containers are managed by a single docker-compose file in the web repo:
`/opt/web/deployment/docker/docker-compose.prod.yml`

This is intentional. The website is the OAuth provider that the MCP server depends on. They share a database. One compose file manages both.

## Deploy MCP Server

After pushing to GitHub:

```bash
# Option A: Run from local machine (convenience wrapper)
bash deployment/scripts/deploy.sh

# Option B: SSH directly
ssh root@64.23.155.158 "bash /opt/web/deployment/scripts/deploy.sh mcp"
```

## Deploy Both Services

```bash
ssh root@64.23.155.158 "bash /opt/web/deployment/scripts/deploy.sh all"
```

## Rollback

```bash
ssh root@64.23.155.158
cd /opt/mcp
git log --oneline -10
git checkout <commit-hash>
bash /opt/web/deployment/scripts/deploy.sh mcp
```

## Logs

```bash
# MCP server logs
docker logs aicc-mcp --tail 100 -f

# Website logs
docker logs aicc-web --tail 100 -f

# From local machine
ssh root@64.23.155.158 "docker logs aicc-mcp --tail 100 -f"
```

## First-Time Setup

See `deployment/scripts/setup.sh` for full instructions. Summary:

1. Provision Ubuntu 24.04 droplet, point DNS
2. Run setup.sh (installs Docker, nginx, creates directories)
3. Clone both repos to /opt/web and /opt/mcp
4. Create .env files (JWT_SECRET must match between both)
5. Install nginx config, setup SSL, setup firewall
6. Deploy: `bash /opt/web/deployment/scripts/deploy.sh all`
7. Add users via admin CLI

## Environment Files

**MCP server** (`/opt/mcp/.env`):
```
AICC_PORT=8443
AICC_DB_PATH=/app/data/aicc.db
AICC_LOG_LEVEL=info
AICC_LOG_DIR=/app/logs
AICC_JWT_SECRET=<must-match-web>
```

**Website** (`/opt/web/.env`):
```
WEB_PORT=8080
DB_PATH=/app/data/aicc.db
JWT_SECRET=<must-match-mcp>
WEB_SECRET_KEY=<separate-random-secret>
COOKIE_SECURE=true
```

The `AICC_JWT_SECRET` (MCP) and `JWT_SECRET` (web) must be the same value. The website issues JWT tokens, the MCP server validates them.

## User Management

```bash
docker exec -it aicc-mcp python -m src.admin.cli list
docker exec -it aicc-mcp python -m src.admin.cli add --name "Name" --email "email" ...
docker exec -it aicc-mcp python -m src.admin.cli disable --key aicc-xxx
docker exec -it aicc-mcp python -m src.admin.cli rotate --email user@example.com
```

## Why No docker-compose.prod.yml in This Repo

The production compose file lives in the web repo (`theintentlayer.com/deployment/docker/docker-compose.prod.yml`). It manages both the website and MCP containers because:

1. They share a database (SQLite at /opt/data/aicc.db)
2. The website is the OAuth provider -- MCP depends on it
3. One compose file prevents container/network/volume drift between services
4. Deploy scripts in both repos point to the same canonical compose

The `deployment/docker/Dockerfile` in this repo is still used -- the web repo's compose references it via `context: /opt/mcp`.
