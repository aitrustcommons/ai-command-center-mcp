# AI Command Center -- MCP Server

A multi-tenant MCP server that gives any MCP-compatible AI client full access to a user's [AI Command Center](https://github.com/aitrustcommons/ai-command-center) system: identity, personalities, status, content, and work items.

## What This Does

The server is a bridge between AI clients and two APIs:

- **GitHub REST API** -- reads and writes files in the user's AiCC repository (identity rules, personalities, status, content)
- **Azure DevOps REST API** -- manages work items (create, update, query, comment, daily logs)

The server is stateless for content. It stores only user configuration (API keys and credentials) in a local SQLite database.

## Supported Clients

Any MCP-compatible client can connect:
- claude.ai (remote MCP connector)
- Microsoft Copilot Chat (via Copilot Studio agent)
- Open WebUI with local LLMs (via HTTP)
- Any tool that speaks MCP over HTTP

## Tools (22)

### Identity (9)
| Tool | Description |
|------|-------------|
| `load_context` | Load full AI partner context for a conversation (identity rules + status + personality + boot files) |
| `get_identity_rules` | Get universal behavioral rules |
| `update_identity_rules` | Update universal behavioral rules |
| `get_current_status` | Get current status across all work areas (read-only) |
| `get_personalities` | List all available personalities |
| `get_personality` | Get behavioral rules for a specific personality |
| `update_personality` | Update behavioral rules for a specific personality |
| `get_recent_activity` | Get recent commits |
| `detect_mode` | Match a message to the best personality via trigger keywords |

### Content (6)
| Tool | Description |
|------|-------------|
| `list_content` | List directory contents |
| `get_document` | Read a document |
| `create_document` | Create a new document |
| `update_document` | Update an existing document |
| `move_document` | Move or rename a document |
| `delete_document` | Delete a document |

### Work Items (7)
| Tool | Description |
|------|-------------|
| `get_tracking_areas` | Get all valid work areas |
| `list_work_items` | List work items with optional filters |
| `get_work_item` | Get full work item details |
| `create_work_item` | Create a new work item |
| `update_work_item` | Update work item fields |
| `add_comment` | Add a comment to a work item |
| `log_daily_summary` | Log a daily summary (find-or-create pattern) |

## Quick Start (Development)

```bash
# Install dependencies
pip install -r requirements.txt

# Initialize the database
python -m src.admin.cli init

# Add a user
python -m src.admin.cli add \
  --name "Your Name" \
  --github-owner your-github-username \
  --github-repo your-aicc-repo \
  --github-pat ghp_your_pat

# Run the server
python -m src.server
```

The server starts on port 8443. All MCP requests go to `POST /mcp` with `Authorization: Bearer <api_key>`.

## Production Deployment

See [deployment/README.md](deployment/README.md) for full deployment instructions. The server runs as a Docker container behind nginx with SSL on a Digital Ocean droplet.

## Authentication

Every request requires an API key in the `Authorization: Bearer <key>` header. Keys are generated via the admin CLI and stored in the SQLite database. User GitHub/AZ DevOps PATs are stored server-side -- clients never see them.

## Running Tests

```bash
pip install pytest pytest-asyncio
pytest tests/ -v
```

## Technology Stack

- Python 3.11+
- FastAPI + MCP Python SDK (`mcp` on PyPI)
- SQLite for user configuration
- httpx for async HTTP calls to GitHub and AZ DevOps APIs
- Docker + nginx for production deployment
