.PHONY: help install migrate makemigrations run worker beat shell test lint format check up down logs

help:
	@echo "make install         - install development dependencies"
	@echo "make migrate         - apply database migrations"
	@echo "make makemigrations  - generate new migrations"
	@echo "make run             - run the dev server"
	@echo "make worker          - run a Celery worker"
	@echo "make beat            - run the Celery beat scheduler"
	@echo "make shell           - open a Django shell (shell_plus if available)"
	@echo "make test            - run the test suite with coverage"
	@echo "make lint            - run ruff + black --check"
	@echo "make format          - apply ruff --fix + black"
	@echo "make check           - django system checks"
	@echo "make up / down / logs - docker compose lifecycle"

install:
	pip install -r requirements/development.txt
	pre-commit install

migrate:
	python manage.py migrate

makemigrations:
	python manage.py makemigrations

run:
	python manage.py runserver 0.0.0.0:8000

worker:
	celery -A config worker -l info

beat:
	celery -A config beat -l info

shell:
	python manage.py shell_plus || python manage.py shell

test:
	pytest

lint:
	ruff check apps config tests manage.py
	black --check apps config tests manage.py

format:
	ruff check --fix apps config tests manage.py
	black apps config tests manage.py

check:
	python manage.py check

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f
