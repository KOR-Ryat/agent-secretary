#!/usr/bin/env bash
# Export Claude Code OAuth credentials from macOS keychain → ~/.claude/.credentials.json
#
# Claude Code stores OAuth tokens in the macOS keychain under the service name
# "Claude Code-credentials". The access token expires every few hours and is
# automatically refreshed by the desktop app. This script pulls the current
# (already-refreshed) token and writes it to a file that the Claude CLI can
# read inside Docker containers (which have no keychain access).
#
# Usage:
#   ./scripts/export-claude-credentials.sh          # explicit run
#   make creds                                       # via Makefile shorthand
#   make up                                          # auto-runs before docker compose up
#
# Prerequisites:
#   - macOS with Claude Code desktop app installed and logged in (MAX plan)
#   - `security` CLI (built into macOS)
#
# Output:
#   ~/.claude/.credentials.json  (mounted into the agents container via docker-compose)

set -euo pipefail

DEST="${HOME}/.claude/.credentials.json"

# Read from keychain
CREDS=$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null) || {
  echo "error: 'Claude Code-credentials' not found in keychain." >&2
  echo "  → Make sure Claude Code is installed and you are logged in." >&2
  exit 1
}

# Validate JSON
echo "$CREDS" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'claudeAiOauth' in d" 2>/dev/null || {
  echo "error: keychain entry does not contain expected claudeAiOauth key." >&2
  exit 1
}

# Show expiry
echo "$CREDS" | python3 -c "
import sys, json, datetime
d = json.load(sys.stdin)
exp = d['claudeAiOauth']['expiresAt']
dt = datetime.datetime.fromtimestamp(exp / 1000, tz=datetime.timezone.utc).astimezone()
delta = dt - datetime.datetime.now(tz=datetime.timezone.utc)
h, r = divmod(int(delta.total_seconds()), 3600)
m = r // 60
print(f'  token expires: {dt.strftime(\"%Y-%m-%d %H:%M %Z\")} ({h}h {m}m remaining)')
"

mkdir -p "$(dirname "$DEST")"
echo "$CREDS" > "$DEST"
echo "  written → $DEST"
