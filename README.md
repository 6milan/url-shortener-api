# URL Shortener API

Django REST Framework + Redis + Celery. See the PDF tutorial for the full walkthrough.

    pip install -r requirements/development.txt
    cp .env.example .env
    docker compose up -d redis        # or: redis-server
    export DJANGO_SETTINGS_MODULE=config.settings.development
    python manage.py migrate
    python manage.py runserver        # terminal 1
    celery -A config worker -l info   # terminal 2
    python manage.py test
