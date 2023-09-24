from typing import Any

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
