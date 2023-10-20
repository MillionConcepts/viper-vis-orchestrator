from functools import wraps
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session


class OSession:
    """
    SQLAlchemy Session manager for VIPER orchestrator. autoinitializes
    database features on entry (if necessary).
    """

    def __enter__(self) -> Session:
        from viper_orchestrator.db.runtime import ENGINE

        self.session = Session(ENGINE)
        return self.session

    def __exit__(self, type_: Any, value: Any, traceback: Any) -> None:
        if self.session is not None:
            self.session.close()
        self.session = None

    session = None


def autosession(func, manager=OSession):
    @wraps(func)
    def with_session(*args, session=None, **kwargs):
        if session is None:
            with manager() as session:
                return func(*args, session=session, **kwargs)
        return func(*args, session=session, **kwargs)

    return with_session


# noinspection PyTypeChecker
@autosession
def get_one(table, value, pivot="id", session=None):
    return session.scalars(
        select(table).where(getattr(table, pivot) == value)
    ).one()
