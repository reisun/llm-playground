.PHONY: test up stop restart logs health

# Run all checks: config validation, lint, format, unit tests
test:
	docker compose config > /dev/null
	cd agent-gateway && .venv/bin/ruff check .
	cd agent-gateway && .venv/bin/ruff format --check .
	cd agent-gateway && .venv/bin/python -m pytest tests/

# Start all services
up:
	docker compose up -d

# Stop all services
stop:
	docker compose stop

# Restart all services
restart:
	docker compose restart

# Show logs
logs:
	docker compose logs -f

# Run full health check
health:
	bash scripts/health-check.sh
