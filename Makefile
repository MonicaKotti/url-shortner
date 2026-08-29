.PHONY: install run test lint check docker-up

install:
	python3 -m pip install -e '.[dev]'

run:
	python3 -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	python3 -m pytest

lint:
	python3 -m ruff check app tests .agents/skills/agentic-sdlc/scripts

check: lint test

docker-up:
	docker compose up --build

