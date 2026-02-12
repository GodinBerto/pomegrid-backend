import logging
import os
from logging.handlers import RotatingFileHandler
from flask import g, request
from time import time


def setup_logging(app):
    os.makedirs("logs", exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )

    file_handler = RotatingFileHandler(
        "logs/app.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    app.logger.setLevel(logging.INFO)
    app.logger.handlers.clear()
    app.logger.addHandler(file_handler)
    app.logger.addHandler(stream_handler)

    @app.before_request
    def start_timer():
        g.request_start_time = time()

    @app.after_request
    def log_response(response):
        elapsed_ms = 0
        if hasattr(g, "request_start_time"):
            elapsed_ms = int((time() - g.request_start_time) * 1000)
        app.logger.info(
            "%s %s %s %sms",
            request.method,
            request.path,
            response.status_code,
            elapsed_ms,
        )
        return response

    @app.errorhandler(Exception)
    def handle_exception(error):
        app.logger.exception("Unhandled exception: %s", error)
        return {"message": "Internal server error"}, 500
