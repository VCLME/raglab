from raglab.db.migrate import upgrade_database
from raglab.db.session import get_engine


def initialize_database() -> None:
    engine = get_engine()
    with engine.begin() as connection:
        upgrade_database(connection)
