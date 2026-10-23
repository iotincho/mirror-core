"""One metadata registry shared by all PostgreSQL capabilities."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
