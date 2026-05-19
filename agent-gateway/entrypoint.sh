#!/bin/bash
set -e

# --- Claude Code authentication ---
# Priority: CLAUDE_SETUP_TOKEN (setup-token OAuth) > host mount (~/.claude)
if [ -n "$CLAUDE_SETUP_TOKEN" ]; then
  export CLAUDE_CODE_OAUTH_TOKEN="$CLAUDE_SETUP_TOKEN"
  export CLAUDE_CONFIG_DIR="$HOME/.claude-server"
  mkdir -p "$CLAUDE_CONFIG_DIR"
else
  # Fallback: symlink host auth directories so token refreshes propagate immediately
  if [ -d /mnt/claude ]; then
    rm -rf "$HOME/.claude"
    ln -s /mnt/claude "$HOME/.claude"
  fi

  # .claude.json is mounted directly via docker-compose volume.
  # Fallback to backup if mount is missing.
  if [ ! -f "$HOME/.claude.json" ]; then
    if ls /mnt/claude/backups/.claude.json.backup.* 1>/dev/null 2>&1; then
      latest=$(ls -t /mnt/claude/backups/.claude.json.backup.* | head -1)
      cp "$latest" "$HOME/.claude.json"
    fi
  fi
fi

# --- GitHub CLI authentication ---
if [ -d /mnt/gh ]; then
  mkdir -p "$HOME/.config"
  rm -rf "$HOME/.config/gh"
  ln -s /mnt/gh "$HOME/.config/gh"
fi

# Use gh as git credential helper so git push works with gh auth
gh auth setup-git 2>/dev/null || true

exec "$@"
