from .connect import create_connect_indexes, create_connect_tables
from .farms import create_farm_indexes, create_farm_tables
from .shared import create_shared_indexes, create_shared_tables
from .workers import create_worker_indexes, create_worker_tables
from .intro import create_intro_tables
from .console import create_console_indexes, create_console_tables
from .food_trade import create_food_trade_indexes, create_food_trade_tables

__all__ = [
    "create_connect_indexes",
    "create_connect_tables",
    "create_farm_indexes",
    "create_farm_tables",
    "create_shared_indexes",
    "create_shared_tables",
    "create_worker_indexes",
    "create_worker_tables",
    "create_intro_tables",
    "create_console_indexes",
    "create_console_tables",
    "create_food_trade_indexes",
    "create_food_trade_tables",
]
