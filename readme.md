# agent-secretary

Multi-agent PR review and code task automation system. Phase 1 goal: accurately classify PRs into **auto-merge / request-changes / escalate-to-human** without human review (escalating only when needed).

## Documents

- [`design.md`](design.md) — PR review system design (personas, dispatcher, CTO, KPIs)
- [`design_server.md`](design_server.md) — server architecture (4-layer pipeline: ingress / core / agents / egress)
- [`prompts/`](prompts/) — system prompts for each persona (1 dispatcher + 5 leads + 19 specialists + 1 CTO)

## Architecture (4 services + Redis + Postgres)

```
external ─→ [ingress] ─Q1→ [core] ─Q2→ [agents] ─Q3→ [egress] ─→ external
              ack             classify    LLM personas + CTO     deliver
```

Each service is independently deployable. See `design_server.md` for details.

## Layout (uv workspace)

```
packages/schemas/                     # shared Pydantic models
services/
  ingress/                            # FastAPI webhook receivers
  core/                               # workflow classifier
  agents/                             # personas + workflow runners + trace store
  egress/                             # channel deliverers
infra/docker-compose.yml              # local dev: redis + postgres + 4 services
prompts/                              # persona system prompts
tests/                                # cross-service smoke tests
```

## Local development

Install everything:

```bash
uv sync --all-packages
```

Run tests (logical pipeline smoke; mocks Anthropic, no Redis/Postgres needed):

```bash
uv run pytest tests/
```

Run the full stack via Docker:

```bash
cp .env.example .env       # then fill in ANTHROPIC_API_KEY (required), GITHUB_*, etc.
cd infra && docker-compose up
```

Trigger a manual review (CLI plugin → core → agents → egress's CLI deliverer):

```bash
curl -X POST http://localhost:8080/channels/cli/submit \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "fix: validate input",
    "changed_files": ["api/items.py"],
    "diff": "--- a/api/items.py\n+++ b/api/items.py\n..."
  }'
```

## Status

Phase 1 (shadow mode): wire-complete. The pipeline ingests PR events, runs the full dispatcher → leads (with specialists) → CTO flow, persists a trace, and posts a markdown summary as a PR comment. **No merge/label/status actions are taken on GitHub.**

Open items (see `design_server.md §11` and `design.md §12`):

- GitHub App / webhook tunnel for live PR testing
- `human_decision` capture webhook + KPI calculation job
- Activation trigger pattern tuning per target codebase
- High-risk path list per codebase

## Models

- CTO: `claude-opus-4-7`
- Dispatcher / leads / specialists: `claude-sonnet-4-6`

Override via `MODEL_CTO` / `MODEL_DEFAULT` env vars.
