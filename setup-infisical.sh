#!/usr/bin/env bash
# setup-infisical.sh — wire a relay machine to pull secrets from Infisical.
#
# Quick start (no clone required):
#
#   curl -fsSL https://raw.githubusercontent.com/eyal-gor/p_69_branch_monkey_mcp/main/setup-infisical.sh | bash
#
# Or if you have the repo cloned:
#
#   bash setup-infisical.sh
#
# What it does:
#   1. Prompts for the 3 (or 4) Infisical values — silent input for the
#      token so it never appears on screen.
#   2. Backs up existing ~/.env to ~/.env-backups/ before touching it.
#   3. Strips old INFISICAL_* lines and writes fresh ones — re-running
#      after rotating a token is safe (no duplicates).
#   4. Wires ~/.zprofile to auto-export ~/.env on shell startup
#      (idempotent — only adds the block once).
#   5. Calls `launchctl setenv` so launchd-spawned processes (LaunchAgents,
#      GUI-launched apps) also inherit the vars.
#   6. Stops any running relay and restarts via `uvx --refresh` against
#      the latest commit on main.

set -euo pipefail

ENV_FILE="${HOME}/.env"
PROFILE_FILE="${HOME}/.zprofile"
BACKUP_DIR="${HOME}/.env-backups"
INFISICAL_KEYS=(INFISICAL_TOKEN INFISICAL_CLIENT_ID INFISICAL_PROJECT_ID INFISICAL_ENV)
RELAY_PKG="git+https://github.com/eyal-gor/p_69_branch_monkey_mcp.git"

cyan()  { printf "\033[36m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
red()   { printf "\033[31m%s\033[0m\n" "$*"; }

# ── 1. Prompt (silent for the secret token) ────────────────────────────
cyan "Infisical setup — values won't be echoed back"

read -r -p "INFISICAL_PROJECT_ID (UUID from URL): " PROJECT_ID
[[ -z "$PROJECT_ID" ]] && { red "project id required"; exit 1; }

read -r -p "INFISICAL_ENV [dev]: " ENVNAME
ENVNAME="${ENVNAME:-dev}"

read -r -s -p "INFISICAL_TOKEN (paste; hidden): " TOKEN; echo
[[ -z "$TOKEN" ]] && { red "token required"; exit 1; }

CLIENT_ID=""
if [[ "$TOKEN" != st.* ]]; then
  read -r -p "INFISICAL_CLIENT_ID (universal-auth client id): " CLIENT_ID
  [[ -z "$CLIENT_ID" ]] && { red "client id required for non-st. tokens"; exit 1; }
fi

# ── 2. Backup ──────────────────────────────────────────────────────────
mkdir -p "$BACKUP_DIR"
if [[ -f "$ENV_FILE" ]]; then
  cp "$ENV_FILE" "${BACKUP_DIR}/.env.$(date +%Y%m%d-%H%M%S).bak"
  green "backed up existing ${ENV_FILE}"
fi

# ── 3. Idempotent rewrite of INFISICAL_* lines ─────────────────────────
# Atomic: write to a tmp file, then move into place.
TMP="$(mktemp -t mini-env)"
if [[ -f "$ENV_FILE" ]]; then
  # Strip existing INFISICAL_* lines from the source.
  grep -vE "^($(IFS=\|; echo "${INFISICAL_KEYS[*]}"))=" "$ENV_FILE" > "$TMP" || true
fi

cat >> "$TMP" <<EOF
INFISICAL_TOKEN=${TOKEN}
INFISICAL_PROJECT_ID=${PROJECT_ID}
INFISICAL_ENV=${ENVNAME}
EOF
[[ -n "$CLIENT_ID" ]] && echo "INFISICAL_CLIENT_ID=${CLIENT_ID}" >> "$TMP"

# Lock down before moving — secrets at rest should be 600.
chmod 600 "$TMP"
mv "$TMP" "$ENV_FILE"
green "wrote ${ENV_FILE} (chmod 600)"

# ── 4. Auto-load in interactive zsh shells (idempotent) ────────────────
SOURCE_LINE='# auto-load ~/.env (added by setup-mini-env.sh)
set -a; [ -f "$HOME/.env" ] && . "$HOME/.env"; set +a'
if ! grep -q 'auto-load ~/.env (added by setup-mini-env.sh)' "$PROFILE_FILE" 2>/dev/null; then
  printf '\n%s\n' "$SOURCE_LINE" >> "$PROFILE_FILE"
  green "added auto-load block to ${PROFILE_FILE}"
else
  green "${PROFILE_FILE} already auto-loads ~/.env"
fi

# ── 5. Push to launchd so non-interactive contexts also see them ───────
# `launchctl setenv` makes future-launched processes inherit. Doesn't
# affect already-running ones — that's why we kill the relay below.
for k in "${INFISICAL_KEYS[@]}"; do
  v="$(grep -E "^${k}=" "$ENV_FILE" | head -1 | cut -d= -f2-)"
  [[ -n "$v" ]] && launchctl setenv "$k" "$v"
done
green "launchctl setenv applied"

# ── 6. Restart the relay against latest main ───────────────────────────
cyan "stopping any running relay…"
pkill -f branch-monkey-relay || true
sleep 1

# Apply the just-written vars to THIS shell so the exec inherits them.
set -a; . "$ENV_FILE"; set +a

cyan "starting relay (uvx --refresh)…"
exec uvx --refresh --from "$RELAY_PKG" branch-monkey-relay
