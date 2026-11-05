from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config


engine = create_engine(config.DATABASE_URL, connect_args={"check_same_thread": False})



@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    """Klasa bazowa"""


def get_db():
    """Daje każdemu zapytaniu HTTP własną sesję i zamyka ją po odpowiedzi."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()