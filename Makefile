COMPOSE = docker compose -f infra/docker-compose.yml --env-file .env

.PHONY: creds up down build logs

## Export Claude OAuth token from macOS keychain → ~/.claude/.credentials.json
creds:
	@echo "==> Exporting Claude credentials from keychain..."
	@bash scripts/export-claude-credentials.sh

## Export credentials then bring up all services
up: creds
	$(COMPOSE) up -d

## Stop all services
down:
	$(COMPOSE) down

## Rebuild all images (no cache)
build:
	$(COMPOSE) build --no-cache

## Tail logs (usage: make logs s=agents)
logs:
	$(COMPOSE) logs -f $(s)
