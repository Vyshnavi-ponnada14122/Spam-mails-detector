import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base

DATABASE_PATH = os.path.join(os.path.dirname(__file__), "spam_app.db")
engine = create_engine(
    f"sqlite:///{DATABASE_PATH}",
    connect_args={"check_same_thread": False},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)

def init_db():
    Base.metadata.create_all(engine)


def get_db_session():
    return SessionLocal()
