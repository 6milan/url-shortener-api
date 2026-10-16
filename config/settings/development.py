"""Local development. Needs a Redis server (docker compose up -d redis)."""
from .base import *  # noqa: F403

DEBUG = True

# Easy local logging of SQL is one line away:
# LOGGING['loggers']['django.db.backends'] = {'level': 'DEBUG'}
LOGGING['root']['level'] = 'DEBUG'  # noqa: F405
LOGGING['loggers']['django.db.backends'] = {'level': 'INFO'}  # noqa: F405

# Print outgoing email to the console instead of sending it.
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
