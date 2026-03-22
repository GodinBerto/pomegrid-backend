from .connection import DB_PATH, db_connection


def create_tables():
    from .bootstrap import create_tables as bootstrap_create_tables

    bootstrap_create_tables()


def initialize_database():
    create_tables()


__all__ = ["DB_PATH", "create_tables", "db_connection", "initialize_database"]
