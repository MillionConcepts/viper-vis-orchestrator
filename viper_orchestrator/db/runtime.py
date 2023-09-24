"""orchestrator-specific database configuration"""

from sqlalchemy import create_engine

from viper_orchestrator.db.config import BASES, TEST_DB_PATH, TEST

if TEST is True:
    ENGINE = create_engine(f"sqlite:///{TEST_DB_PATH}")
else:
    raise NotImplementedError  # postgresql
# TODO: this should be harmless, make sure it is
for base in BASES:
    base.metadata.create_all(ENGINE)


# TODO: replace this with functionality from vipersci once implemented
def sqlite_monkeypatch_rawproduct():
    """
    monkeypatch RawProduct to cause its as_dict method to return tz-aware
    datetimes. intended for testing with sqlite (SQLAlchemy's sqlite backend
    does not store datetimes as tz-aware even if you ask it to).

    TODO: copied from higher level pending module organization
    """
    import datetime as dt

    import vipersci.vis.db.image_records
    from vipersci.pds.datetime import isozformat

    def asdict(self):
        d = {}

        for c in self.__table__.columns:
            if isinstance(getattr(self, c.name), dt.datetime):
                date_time = getattr(self, c.name).replace(
                    tzinfo=dt.timezone.utc
                )
                d[c.name] = isozformat(date_time)
            else:
                d[c.name] = getattr(self, c.name)

        # the SQLAlchemy metaclass constructor does not consistently call the
        # class's __init__ method on db retrieval, so only attempt to merge
        # labelmeta if it actually exists
        if "labelmeta" in dir(self):
            d.update(self.labelmeta)

        return d

    vipersci.vis.db.image_records.ImageRecord.asdict = asdict


if TEST is True:
    sqlite_monkeypatch_rawproduct()
