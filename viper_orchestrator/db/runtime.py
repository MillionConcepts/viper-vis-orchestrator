"""orchestrator-specific database configuration"""
import atexit
import shutil
import time
from functools import partial
from pathlib import Path

from hostess.subutils import Viewer, run
from sqlalchemy import create_engine, select, insert
from sqlalchemy.orm import Session

from viper_orchestrator.db.config import BASES, TEST_DB_PATH, TEST
from vipersci.vis.db.image_tags import ImageTag, taglist

INITIALIZED_DB = False
KILL_TARGETS = []
DO_NOT_KILL = []


def listkiller(processes: list[Viewer]):
    if len(processes) > 0:
        print('killing managed processes...')
    while len(processes) > 0:
        viewer = processes.pop()
        print(f"killing PID {viewer.pid} ({viewer.command})...", end="")
        viewer.kill()
        viewer.wait()
        print(f"killed")


atexit.register(partial(listkiller, KILL_TARGETS))

if TEST is True:
    if not Path(TEST_DB_PATH).exists():
        INITIALIZED_DB = True
        for cmd in (
            f"initdb -D {TEST_DB_PATH}",
            f"postgres -D {TEST_DB_PATH}",
            f'psql -d {TEST_DB_PATH.name} -c "CREATE EXTENSION postgis"',
            f"""psql -d {TEST_DB_PATH.name} -c "INSERT into spatial_ref_sys (srid, auth_name, auth_srid, proj4text) values ( 910101, 'VIPER', 910101, '+proj=stere +lat_0=-85.42088 +lon_0=31.6218 +R=1737400 +units=m')\"""",
        ):
            pginit = Viewer.from_command(cmd)
            if cmd.startswith("postgres -D"):
                POSTGRES_PID = pginit.pid
                time.sleep(1)
                if (
                    "database system is ready to accept connections" not
                    in pginit.err[-1]
                ):
                    print('removing db path')
                    shutil.rmtree(TEST_DB_PATH)
                    pginit.kill()
                    raise OSError(
                        f"postgres server process failed to launch:\n\n"
                        f"{','.join(pginit.err)}"
                    )
                KILL_TARGETS.append(pginit)
            else:
                pginit.wait()
                if pginit.returncode() != 0:
                    print('removing db path')
                    shutil.rmtree(TEST_DB_PATH)
                    raise OSError(
                        f"postgres database failed to initialize\ncommand "
                        f"{pginit.command} failed:\n\n{','.join(pginit.err)}"
                    )
    else:
        pginit = Viewer.from_command(f"postgres -D {TEST_DB_PATH}")
        time.sleep(1)
        if (
            "database system is ready to accept connections" not
            in pginit.err[-1]
        ):
            # if it fails with the "another server might be running" message,
            # assume we already launched it on purpose. i.e., don't kill it
            # when we leave...
            if "another server might be running" not in pginit.stderr[0]:
                pginit.kill()
                raise OSError(
                    f"postgres server process failed to launch:\n"
                    f"{','.join(pginit.err)}"
                )
            # ...but make sure we can still access it if we like.
            DO_NOT_KILL.append(pginit)
        else:
            KILL_TARGETS.append(pginit)
    ENGINE = create_engine(f"postgresql:///{TEST_DB_PATH.name}")
else:
    raise NotImplementedError  # system-level postgresql server

# TODO: this should be harmless, make sure it is
for base in BASES:
    base.metadata.create_all(ENGINE)


def set_up_tags():
    """semi-vendored from vipersci"""
    with Session(ENGINE) as session:
        # Establish image_tags
        scalars = session.scalars(select(ImageTag))
        results = scalars.all()
        if len(results) == 0:
            session.execute(insert(ImageTag), [{"name": x} for x in taglist])
            session.commit()
        elif len(results) == len(taglist):
            for i, row in enumerate(results):
                if row.name != taglist[i]:
                    raise ValueError(
                        f"Row {i} in the database has id {row.id} and tag "
                        f"{row.name} but should have {taglist[i]} from "
                        f"{taglist}."
                    )
        else:
            raise ValueError(
                f"The {ImageTag.__tablename__} table already contains the "
                f"following {len(results)} entries: "
                f"{[r.name for r in results]}, but should "
                f"contain these {len(taglist)} entries: {taglist}"
            )


set_up_tags()


# TODO: following is probably cruft now
# def sqlite_monkeypatch_rawproduct():
#     """
#     monkeypatch RawProduct to cause its as_dict method to return tz-aware
#     datetimes. intended for testing with sqlite (SQLAlchemy's sqlite backend
#     does not store datetimes as tz-aware even if you ask it to).
#
#     TODO: copied from higher level pending module organization
#     """
#     import datetime as dt
#
#     import vipersci.vis.db.image_records
#     from vipersci.pds.datetime import isozformat
#
#     def asdict(self):
#         d = {}
#
#         for c in self.__table__.columns:
#             if isinstance(getattr(self, c.name), dt.datetime):
#                 date_time = getattr(self, c.name).replace(
#                     tzinfo=dt.timezone.utc
#                 )
#                 d[c.name] = isozformat(date_time)
#             else:
#                 d[c.name] = getattr(self, c.name)
#
#         # the SQLAlchemy metaclass constructor does not consistently call the
#         # class's __init__ method on db retrieval, so only attempt to merge
#         # labelmeta if it actually exists
#         if "labelmeta" in dir(self):
#             d.update(self.labelmeta)
#
#         return d
#
#     vipersci.vis.db.image_records.ImageRecord.asdict = asdict
#
#
# if TEST is True:
#     sqlite_monkeypatch_rawproduct()
