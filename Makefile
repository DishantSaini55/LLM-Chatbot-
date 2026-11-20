.PHONY: up down test

up:
	docker compose up --build

down:
	docker compose down

test:
	uv run --project backend pytest backend/tests -q
