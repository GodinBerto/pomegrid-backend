from flask import Blueprint

console_bp = Blueprint("console", __name__)

from . import roles, categories, expenses, budgets, reports, workers, overview, analytics, settings, notifications
