.PHONY: install seed run web test lint build docker-up

install:
	uv sync --extra dev
	cd frontend && npm install

seed:
	uv run python scripts/seed_demo_data.py

run:            ## API on :8000
	uv run uvicorn backend.app.main:app --reload --port 8000

web:            ## UI on :5173 (proxies /api to :8000)
	cd frontend && npm run dev

test:
	uv run pytest -q

lint:
	uv run ruff check backend scripts

build:
	cd frontend && npm run build

docker-up:
	docker compose up --build
