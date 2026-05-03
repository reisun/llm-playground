#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== Docker Compose config check ==="
if docker compose config > /dev/null 2>&1; then
  echo "OK: docker-compose.yml is valid"
else
  echo "FAIL: docker-compose.yml has errors"
  docker compose config
  exit 1
fi

echo ""
echo "=== Container status ==="
if docker compose ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null; then
  echo ""
else
  echo "INFO: No containers running (run 'docker compose up -d' to start)"
fi

echo ""
echo "=== Ollama API check ==="
if curl -sf http://localhost:11434 > /dev/null 2>&1; then
  echo "OK: Ollama is responding"
else
  echo "INFO: Ollama is not responding (may not be running)"
fi

echo ""
echo "=== Open WebUI check ==="
WEBUI_PORT="${WEBUI_PORT:-3000}"
if curl -sf "http://localhost:${WEBUI_PORT}" > /dev/null 2>&1; then
  echo "OK: Open WebUI is responding on port ${WEBUI_PORT}"
else
  echo "INFO: Open WebUI is not responding (may not be running)"
fi

echo ""
echo "Health check complete."
