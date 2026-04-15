from sqlalchemy import text

from raglab.db.base import Base
from raglab.db.session import get_engine


def initialize_database() -> None:
    engine = get_engine()
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
