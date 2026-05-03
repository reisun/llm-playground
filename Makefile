.PHONY: test up stop restart logs health

# Validate docker-compose.yml syntax
test:
	docker compose config > /dev/null

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
