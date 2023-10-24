from functools import wraps
from typing import Any, Optional

from sqlalchemy.orm import Session


class OSession:
    """
    SQLAlchemy Session manager for VIPER orchestrator. autoinitializes
    database features on entry (if necessary).

    TODO, maybe: replace with a more standard SQLAlchemy sessionmaker object
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
    """
    decorator that causes a function with a keyword-only argument 'session'
    to create its own Session if and only if it does not receive a value for
    that argument.

    this is basically just syntactic sugar and insurance. more sophisticated
    alternatives like Sessions in thread-local scope are unfortunately likely
    to create hard-to-diagnose problems when interacting with either gunicorn
    or hostess.

    Note that unlike those more sophisticated alternatives, when autosession
    kicks in, any DeclarativeBase instances the wrapped function returns
    will be detached, which is in many instances ok, but will break workflows
    that rely on accessing related fields. in these cases, you should always
    explicitly pass an open Session to the function and manage its lifecycle
    yourself (perhaps via higher-level autosession behavior).
    """

    @wraps(func)
    def with_autosession(*args, session: Optional[Session] = None, **kwargs):
        if session is not None:
            return func(*args, session=session, **kwargs)
        with manager() as session:
            return func(*args, session=session, **kwargs)

    return with_autosession
