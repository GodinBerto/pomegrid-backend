from pathlib import Path
import sqlite3


DB_PATH = Path("instance") / "pomegrid.db"


def db_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection, connection.cursor()
