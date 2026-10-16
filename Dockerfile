FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production

WORKDIR /app

COPY requirements/ requirements/
RUN pip install --no-cache-dir -r requirements/production.txt

COPY . .

# collectstatic needs the settings to import, so give it throwaway values.
RUN SECRET_KEY=build-only-$(python -c "import secrets;print(secrets.token_urlsafe(60))") \
    ALLOWED_HOSTS=localhost CORS_ALLOWED_ORIGINS=http://localhost \
    SHORT_URL_BASE=http://localhost DATABASE_URL=sqlite:////tmp/build.sqlite3 \
    python manage.py collectstatic --noinput

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", \
     "--workers", "3", "--timeout", "30", "--access-logfile", "-"]
