# agent-secretary

Multi-agent system for automated code work over Slack and GitHub.

Two workflow shapes today:

- **`pr_review`** — GitHub PR webhook → dispatcher + 5 leads (24 specialists) + CTO → posts markdown summary on the PR. Shadow mode: comments only, no merge/label.
- **`code_analyze` / `code_modify` / `linear_issue`** — Slack `@mention` → single Claude Agent SDK invocation against bare-repo worktrees → `{메시지, 파일}` reply in thread. `code_modify` and `linear_issue` are placeholders.

## Documents

- [`design.md`](design.md) — PR review system design (personas, dispatcher, CTO, KPIs)
- [`design_server.md`](design_server.md) — server architecture (4-layer pipeline)
- [`docs/workspace.md`](docs/workspace.md) — bare repo + worktree setup
- [`prompts/`](prompts/) — system prompts (1 dispatcher + 5 leads + 20 specialists + 1 CTO + 3 workflows)

## Architecture (4 services + Redis + Postgres)

```
external ─→ [ingress] ─Q1→ [core] ─Q2→ [agents] ─Q3→ [egress] ─→ external
              ack             classify    workflows + agents      deliver
              dashboard       (pr_review, code_analyze, ...)
```

Channels (input + output) are plugins:

| Channel | Ingress (input) | Egress (output) |
|---|---|---|
| GitHub | webhook (HMAC) | PR comment |
| Slack | Socket Mode + buttons + thread fetch | message + file (`result.md`) + reactions (⌛/✅/❌) |
| CLI | HTTP POST | stdout |

Each service is independently deployable. See [`design_server.md`](design_server.md) for details.

## Layout (uv workspace)

```
packages/
  schemas/                        # shared Pydantic models
  config/                         # streams, workflows, review_rules,
                                  # service_map (service↔repo↔channel)
services/
  ingress/                        # FastAPI; channel parsers + dashboard
  core/                           # workflow classifier
  agents/                         # personas + workflow runners + workspace skill + trace store
  egress/                         # channel deliverers
infra/docker-compose.yml          # local dev: redis + postgres + 4 services
prompts/                          # persona + workflow system prompts
docs/                             # workspace setup, etc.
tests/                            # cross-service smoke tests (40 tests)
```

## Local development

```bash
uv sync --all-packages
uv run pytest tests/                    # 40 logical/unit tests, no infra required
```

Full stack via Docker:

```bash
cp .env.example .env                    # fill in ANTHROPIC_API_KEY (required) + GITHUB_* + SLACK_*
cd infra && docker-compose up
# → ingress on :8080, dashboard on http://localhost:8080/
```

Trigger a manual PR review (CLI plugin):

```bash
curl -X POST http://localhost:8080/channels/cli/submit \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "fix: validate input",
    "changed_files": ["api/items.py"],
    "diff": "--- a/api/items.py\n+++ b/api/items.py\n..."
  }'
```

For Slack: configure your Slack app with Socket Mode + `app_mentions:read` / `chat:write` / `files:write` / `reactions:write` / `channels:history`, drop the tokens into `.env`, and `@mention` the bot in a registered channel (see [`packages/config/agent_secretary_config/service_map.py`](packages/config/agent_secretary_config/service_map.py)).

## Status

Wire-complete:

- 4-service pipeline over Redis Streams + DLQs
- PR review pipeline (dispatcher → 5 leads + specialists → CTO) writing trace to Postgres
- Slack channel (Socket Mode in, web client + reactions out)
- `code_analyze` workflow with Claude Agent SDK + bare-repo + worktree isolation
- Dashboard (`/`) listing recent traces with workflow / decision / summary

Open items:

- GitHub App / webhook tunnel for live PR testing
- `human_decision` capture webhook + KPI calculation job
- `code_modify` / `linear_issue` real implementations (placeholders today)
- Activation trigger / high-risk path tuning per target codebase

## Models

- CTO: `claude-opus-4-7`
- Dispatcher / leads / specialists / `code_analyze`: `claude-sonnet-4-6`

Override via `MODEL_CTO` / `MODEL_DEFAULT` env vars.
