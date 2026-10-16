import json
import logging


class JsonFormatter(logging.Formatter):
    # One JSON object per line: easy to ship to Loki, ELK, CloudWatch, Datadog...
    def format(self, record):
        payload = {
            'time': self.formatTime(record, '%Y-%m-%dT%H:%M:%S%z'),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)
        return json.dumps(payload)
