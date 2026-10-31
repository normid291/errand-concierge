.PHONY: install dev test lint run docker

install:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements-dev.txt

dev:
	.venv/bin/uvicorn app.main:app --reload --port 8000

test:
	.venv/bin/python -m pytest

lint:
	.venv/bin/ruff check app tests

run:
	.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

docker:
	docker build -t errand-concierge .
	docker run --rm -p 8000:8000 --env-file .env errand-concierge
