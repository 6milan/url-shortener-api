export DJANGO_SETTINGS_MODULE ?= config.settings.development

.PHONY: install redis migrate run worker beat test check

install:
	pip install -r requirements/development.txt

redis:
	docker compose up -d redis

migrate:
	python manage.py migrate

run:
	python manage.py runserver

worker:
	celery -A config worker -l info

beat:
	celery -A config beat -l info

test:
	python manage.py test

check:
	DJANGO_SETTINGS_MODULE=config.settings.production python manage.py check --deploy
